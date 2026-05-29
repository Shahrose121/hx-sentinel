"""
Rebuild job_database.json clean-state fields from results CSVs.

For each job, locate results/results_{id}.csv and find the FIRST row where
FoulResCS == 0 AND FoulResHS == 0 — that is the truly clean baseline.

Pull from that row:
    u_clean   ← HeatTranRatClean
    f_factor  ← MTDCorrFactor
    area      ← Area
    lmtd_design ← LMTD   (used as design LMTD reference)

Print a per-job diff vs current database, then write the rebuilt DB to
job_database.json (BOM preserved). Pass --dry-run to skip the write.
"""
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "job_database.json"
RESULTS_DIR = ROOT / "results"

DRY = "--dry-run" in sys.argv

with open(DB_PATH, encoding="utf-8-sig") as f:
    db = json.load(f)


def read_clean_row(job_id: str):
    csv_path = RESULTS_DIR / f"results_{job_id}.csv"
    if not csv_path.exists():
        # Some jobs keep their CSV at repo root rather than in results/
        alt = ROOT / f"results_{job_id}.csv"
        if alt.exists():
            csv_path = alt
        else:
            return None, f"missing CSV: results_{job_id}.csv"
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                fcs = float(row["FoulResCS"])
                fhs = float(row["FoulResHS"])
            except (KeyError, ValueError):
                continue
            if fcs == 0.0 and fhs == 0.0:
                return row, None
    return None, f"no clean row (FoulResCS=0 AND FoulResHS=0) in {csv_path.name}"


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def approx_eq(a, b, rel=1e-4):
    if a is None or b is None:
        return a == b
    if a == 0 and b == 0:
        return True
    return abs(a - b) / max(abs(a), abs(b), 1e-12) <= rel


updates = 0
problems = []
print(f"{'JOB':<10} {'field':<14} {'db_value':>14} {'csv_value':>14}  {'status'}")
print("-" * 70)

for job in db:
    jid = job["job_id"]
    row, err = read_clean_row(jid)
    if err:
        problems.append((jid, err))
        print(f"{jid:<10} {'-':<14} {'-':>14} {'-':>14}  ERROR: {err}")
        continue

    mapping = {
        "u_clean":         ("HeatTranRatClean",   4),
        "u_service_clean": ("HeatTranRatService", 4),
        "f_factor":        ("MTDCorrFactor",      6),
        "area":            ("Area",               5),
        "lmtd_design":     ("LMTD",               4),
    }

    for db_key, (csv_key, ndp) in mapping.items():
        csv_val = fnum(row.get(csv_key))
        db_val  = fnum(job.get(db_key))
        if csv_val is None:
            print(f"{jid:<10} {db_key:<14} {str(db_val):>14} {'?':>14}  MISSING in CSV ({csv_key})")
            continue
        match = approx_eq(db_val, csv_val)
        tag = "ok" if match else "UPDATED"
        if not match:
            updates += 1
            db_display = f"{db_val:>14.6f}" if db_val is not None else f"{'(new)':>14}"
            print(f"{jid:<10} {db_key:<16} {db_display} {csv_val:>14.6f}  {tag}")
        job[db_key] = round(csv_val, ndp)

print("-" * 70)
print(f"Updated fields: {updates}")
print(f"Jobs with problems: {len(problems)}")

if DRY:
    print("\n--dry-run: not writing job_database.json")
else:
    # preserve BOM that PowerShell-generated JSON used
    with open(DB_PATH, "w", encoding="utf-8-sig") as fh:
        json.dump(db, fh, indent=4)
    print(f"\nWrote {DB_PATH}")
