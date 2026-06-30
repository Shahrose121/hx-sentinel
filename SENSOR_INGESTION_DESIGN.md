# Sensor Ingestion Pipeline — Architecture Design
**Phase 3 (Live Data Feed) — Design Only. Nothing built yet.**

---

## Guiding Principle

The single invariant the entire design enforces: **the ML model never sees a raw sensor value**.
Every number that reaches `/predict` must have passed through the same 4-step validation gate
and the same physics pipeline that manual entry goes through today. The sensor ingestor is not
a shortcut into the model — it is a pre-filter before the existing pipeline.

---

## Pipeline Stages

```
Sensor Source (future API)
        │
        ▼
┌─────────────────────────────────┐
│  STAGE 1: Raw Ingest            │  Store everything, timestamp it.
│  Table: sensor_raw              │  Never discard, never transform here.
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  STAGE 2: Validation Gate       │  All checks run here. On any failure:
│  (new API endpoint)             │  write to sensor_flagged with reason
│                                 │  code. Stop. Do not proceed.
│  2a. Range check                │
│  2b. Pressure inversion guard   │  (already in dashboard — move to API)
│  2c. Temperature cross guard    │  (already in dashboard — move to API)
│  2d. Rate-of-change check       │  compare to previous raw row
│  2e. Staleness check            │  count consecutive identical values
└─────────────────────────────────┘
        │ (only clean readings pass)
        ▼
┌─────────────────────────────────┐
│  STAGE 3: Aggregation           │  If sub-daily: accumulate readings.
│                                 │  At daily boundary (or N readings):
│  - Average temperatures         │    compute daily averages.
│  - Average flows                │    extract peak ΔP separately.
│  - Average pressures            │    mark batch complete.
│  - Peak ΔP retained separately  │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  STAGE 4: Physics Pipeline      │  Identical to manual entry path.
│  (existing /fluid_props calls)  │  REFPROP → enthalpy → Q, LMTD,
│                                 │  U_actual, tube vel, shell nozzle RhoV²
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│  STAGE 5: ML + Override Layer   │  Existing /predict → GBM model.
│  (existing code, unchanged)     │  Existing physics safety overrides.
│                                 │  Write result to existing readings table.
└─────────────────────────────────┘
```

---

## Database Schema — Two New Tables

Both tables are added to `readings.db` alongside the existing `readings` table.

### `sensor_raw` — append-only, every reading stored

```sql
CREATE TABLE sensor_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at     TEXT NOT NULL,          -- UTC ISO-8601, when we got it
    sensor_ts       TEXT NOT NULL,          -- timestamp from sensor system itself
    job_id          TEXT NOT NULL,
    shell_in        REAL,
    shell_out       REAL,
    tube_in         REAL,
    tube_out        REAL,
    shell_flow      REAL,
    tube_flow_scmh  REAL,
    shell_pres_in   REAL,
    shell_pres_out  REAL,
    tube_pres_in    REAL,
    tube_pres_out   REAL,
    source          TEXT,                   -- e.g. 'SCADA', 'OPC-UA', 'Modbus'
    raw_payload     TEXT                    -- JSON blob of whatever came in verbatim
);
```

### `sensor_flagged` — nothing silently discarded

```sql
CREATE TABLE sensor_flagged (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_raw_id   INTEGER REFERENCES sensor_raw(id),
    flagged_at      TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    reason_code     TEXT NOT NULL,          -- see reason codes below
    reason_detail   TEXT,                   -- e.g. "shell_in=220.5 > 200°C"
    field_name      TEXT,                   -- which field triggered the flag
    field_value     REAL,
    previous_value  REAL,                   -- populated for rate-of-change flags
    reviewed        INTEGER DEFAULT 0,      -- 0=pending, 1=confirmed OK, 2=rejected
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    override_note   TEXT                    -- operator comment if confirmed despite flag
);
```

---

## Validation Gate — Reason Codes

| Code | Check | Condition | Behaviour |
|---|---|---|---|
| `RANGE_TEMP` | Range | temp < -50°C or > 200°C | Flag + hard stop |
| `RANGE_PRESSURE` | Range | pressure < 0 or > 200 barg | Flag + hard stop |
| `RANGE_FLOW` | Range | flow < 0 | Flag + hard stop |
| `PRESSURE_INVERSION` | Existing guard | outlet P ≥ inlet P (either side) | Flag + hard stop |
| `TEMP_CROSS` | Existing guard | tube_out > shell_in or shell_out < tube_in | Flag + hard stop |
| `RATE_OF_CHANGE` | Rate check | any field changes > X% from previous reading | Flag, hold for review |
| `FROZEN_SENSOR` | Staleness | same value for ≥ N consecutive readings | Flag, hold for review |

**Hard stop vs. soft flag:**
- `RANGE_*`, `PRESSURE_INVERSION`, `TEMP_CROSS` — physically impossible or instrument failure.
  Reading is discarded from auto-processing. Stored in `sensor_flagged` for the audit trail only.
- `RATE_OF_CHANGE`, `FROZEN_SENSOR` — reading may be valid (genuine process upset or true steady
  state) but requires a human or confirmed-anomaly rule to proceed. Held in `sensor_flagged` with
  `reviewed = 0` until an operator confirms or rejects it.

---

## Configurable Thresholds (per job)

Stored in `job_database.json` alongside the design values so each exchanger has appropriate limits
rather than global defaults:

```json
{
  "job_id": "8497",
  "sensor_config": {
    "rate_change_pct": 15,
    "frozen_count":    6,
    "aggregation_interval": "daily",
    "peak_dp_retained": true
  }
}
```

- `rate_change_pct` — flag if any field changes more than this percentage from the previous reading
  in one polling interval. 15% is a reasonable starting point: a genuine process upset is plausible
  but calibration failure or a stuck valve is more likely above this threshold.
- `frozen_count` — flag after this many consecutive identical readings. At typical 10-minute polling
  a count of 6 means the sensor has been frozen for an hour.
- `aggregation_interval` — `"daily"` or `"hourly"`. Controls when the aggregation step fires.
- `peak_dp_retained` — whether to store peak ΔP separately from the averaged ΔP (should always
  be true for fouling monitoring).

---

## Aggregation Logic (sub-daily data)

When the sensor polls more frequently than daily, Stage 3 accumulates validated readings and
produces one row per aggregation interval:

```
Incoming hourly readings (post-validation)
        │
        ├── AVERAGE: shell_in, shell_out, tube_in, tube_out
        │            shell_flow, tube_flow_scmh
        │            shell_pres_in, shell_pres_out
        │            tube_pres_in,  tube_pres_out
        │
        └── PEAK (max over interval):
                     shell_dp = max(shell_pres_in - shell_pres_out)
                     tube_dp  = max(tube_pres_in  - tube_pres_out)
                     [stored in aggregated row alongside averages — not used in duty calc]
```

The daily-averaged row enters the existing physics pipeline exactly as a manual reading would.
Peak ΔP is retained as an early-warning indicator: if peak ΔP is consistently near the allowable
even while the daily average looks healthy, fouling is progressing. It does not replace the
averaged ΔP in the duty or ML calculation — mixing time bases would corrupt U_actual.

---

## Convergence With Manual Entry

The existing pipeline has two entry points. Both must converge at the same physics layer:

```
Manual entry (today)              Sensor ingest (future)
       │                                  │
       │  existing JS guards              │  Stage 1–3 (new)
       │                                  │
       └──────────────┬───────────────────┘
                      │
              /fluid_props × 3 calls
              Q, LMTD, U_actual, tube vel, shell nozzle RhoV²
              (existing, unchanged)
                      │
              /predict — GBM classifier + regressor
              (existing, unchanged)
                      │
              physics safety overrides
              (existing, unchanged)
                      │
              readings table
              (existing, unchanged)
```

Nothing in Stages 1–3 touches the ML model.
Nothing in Stages 4–5 is new code.
The sensor ingestor is purely a filter that decides whether a batch of raw values is clean enough
to hand off to the pipeline already validated in production.

---

## Implementation Order (when Phase 3 begins)

1. Add `sensor_raw` and `sensor_flagged` tables to `_init_readings_db()` in `api.py`
2. `POST /ingest_reading` — new Flask endpoint; runs validation gate; writes to `sensor_raw`;
   writes flags to `sensor_flagged`; stops there. Does not call physics or ML.
3. `POST /process_pending` — picks up validated (unflagged) raw rows; runs aggregation if
   sub-daily; then calls the existing physics + predict pipeline exactly as the dashboard does.
4. Review endpoint — `GET /flagged`, `POST /flagged/{id}/confirm` — so operators can inspect and
   release soft-flagged readings.
5. Scheduler — APScheduler (in-process) or Windows Task Scheduler calling the API — to poll the
   sensor source and call `/ingest_reading` at the configured interval.

Steps 2–3 are the only new logic. Steps 4–5 are plumbing around existing code.

---

*Phase 3 — not built. Pending real sensor source. Design agreed 2026-06-30.*
