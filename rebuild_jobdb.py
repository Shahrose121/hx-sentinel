"""
Rebuild job_database.json from the EDR CSV clean row (FoulResCS=0 AND FoulResHS=0).

This run uses the full v2 schema requested by the operator:
  shell_flow_design_kgh, tube_flow_design_kgh, tube_flow_design_scmh
  shell_in_design, shell_out_design, tube_in_design, tube_out_design
  shell_press_design_barg, tube_press_in_design_barg
  duty_design_kw, u_clean, u_service_clean, f_factor, area_m2, lmtd_design
  tube_vel_design, rv2_design
  tube_count, tube_od_mm, tube_id_mm, tube_lng_mm, shell_id_mm
  baf_num, baf_spc_mm, baf_cut_pct, tube_pass
  film_coef_ss, film_coef_ts
  foul_res_ss_design, foul_res_ts_design
  dp_allow_shell_bar, dp_allow_tube_bar
  excess_surf_clean_pct
  std_density (0.72838 for Bacton gas), glycol_pct (40 default), cal_factor (1)

Existing v1 field names are preserved as aliases so the dashboard's MAP keeps
working without modification.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "job_database.json"
RESULTS_DIR = ROOT / "results"

DRY = "--dry-run" in sys.argv
STD_DENSITY_DEFAULT = 0.72838     # Mean Bacton Gas at standard conditions

with open(DB_PATH, encoding="utf-8-sig") as f:
    db = json.load(f)


def read_clean_row(job_id: str):
    csv_path = RESULTS_DIR / f"results_{job_id}.csv"
    if not csv_path.exists():
        alt = ROOT / f"results_{job_id}.csv"
        if alt.exists():
            csv_path = alt
        else:
            return None, f"missing CSV: results_{job_id}.csv"
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                if float(row["FoulResCS"]) == 0 and float(row["FoulResHS"]) == 0:
                    return row, None
            except (KeyError, ValueError):
                continue
    return None, f"no clean row in {csv_path.name}"


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# (v2 field, CSV column, decimal places).  Special handling: PresOperInTS gives
# inlet pressure; tube outlet press is in - PresDropCalcTS.
V2_FIELDS = [
    ("shell_flow_design_kgh",      "FlRaTotalSS",          4),
    ("tube_flow_design_kgh",       "FlRaTotalTS",          4),
    ("shell_in_design",            "TempInSS",             4),
    ("shell_out_design",           "TempOutSS",            4),
    ("tube_in_design",             "TempInTS",             4),
    ("tube_out_design",            "TempOutTS",            4),
    ("shell_press_design_barg",    "PresOperInSS",         4),
    ("tube_press_in_design_barg",  "PresOperInTS",         4),
    ("duty_design_kw",             "HtLdTotal",            4),
    ("u_clean",                    "HeatTranRatClean",     4),
    ("u_service_clean",            "HeatTranRatService",   4),
    ("f_factor",                   "MTDCorrFactor",        6),
    ("area_m2",                    "Area",                 5),
    ("lmtd_design",                "LMTD",                 4),
    ("tube_vel_design",            "VelThruTubesMaxTS",    4),
    ("rv2_design",                 "RV2InNoz",             4),
    ("tube_count",                 "TubeNum",              0),
    ("tube_od_mm",                 "TubeOD",               4),
    ("tube_id_mm",                 "TubeID",               4),
    ("tube_lng_mm",                "TubeLng",              4),
    ("shell_id_mm",                "ShlID",                4),
    ("baf_num",                    "BafNum",               0),
    ("baf_spc_mm",                 "BafSpcCC",             4),
    ("baf_cut_pct",                "BafCutPerc",           4),
    ("tube_pass",                  "TubePassNum",          0),
    ("film_coef_ss",               "FilmCoefSS",           4),
    ("film_coef_ts",               "FilmCoefTS",           4),
    ("foul_res_ss_design",         "FoulResSS",            8),
    ("foul_res_ts_design",         "FoulResTS",            8),
    ("dp_allow_shell_bar",         "PresDropAlloSS",       6),
    ("dp_allow_tube_bar",          "PresDropAlloTS",       6),
    ("excess_surf_clean_pct",      "ExcessSurfClean",      4),
]

# v1 → v2 aliases the dashboard still reads.  We populate both.
V1_ALIASES = {
    "shell_in":         "shell_in_design",
    "tube_in":          "tube_in_design",
    "shell_flow":       "shell_flow_design_kgh",
    "tube_flow_kgh":    "tube_flow_design_kgh",
    "shell_pres_in":    "shell_press_design_barg",
    "tube_pres_in":     "tube_press_in_design_barg",
    "duty_design":      "duty_design_kw",
    "area":             "area_m2",
    "tube_num":         "tube_count",
    "tube_od":          "tube_od_mm",
    "tube_id":          "tube_id_mm",
    "tube_lng":         "tube_lng_mm",
    "shl_id":           "shell_id_mm",
    "baf_spc":          "baf_spc_mm",
    "baf_cut":          "baf_cut_pct",
    "vel_ts_design":    "tube_vel_design",
    "rv2_nozzle_design":"rv2_design",
    "dp_allow_ss":      "dp_allow_shell_bar",
    "dp_allow_ts":      "dp_allow_tube_bar",
}


problems = []
print(f"Rebuilding {len(db)} jobs from CSV clean rows...\n")

for job in db:
    jid = job["job_id"]
    row, err = read_clean_row(jid)
    if err:
        problems.append((jid, err))
        print(f"  {jid:<10}  ERROR: {err}")
        continue

    # v2 schema
    for v2_key, csv_key, ndp in V2_FIELDS:
        val = fnum(row.get(csv_key))
        if val is None:
            # Don't clobber existing data with None — skip silently
            continue
        job[v2_key] = round(val, ndp) if ndp > 0 else int(round(val))

    # Tube outlet pressure derived from CSV inlet pressure and tube-side ΔP.
    p_in = fnum(row.get("PresOperInTS"))
    dp_t = fnum(row.get("PresDropCalcTS"))
    if p_in is not None and dp_t is not None:
        job["tube_press_out_design_barg"] = round(p_in - dp_t, 4)
    # Same for shell outlet pressure
    p_in_s = fnum(row.get("PresOperInSS"))
    dp_s = fnum(row.get("PresDropCalcSS"))
    if p_in_s is not None and dp_s is not None:
        job["shell_press_out_design_barg"] = round(p_in_s - dp_s, 6)

    # Computed fields
    std_dens = float(job.get("std_density", STD_DENSITY_DEFAULT) or STD_DENSITY_DEFAULT)
    job["std_density"] = std_dens
    job["glycol_pct"]  = job.get("glycol_pct", 40)
    job["cal_factor"]  = job.get("cal_factor", 1.0)
    if "tube_flow_design_kgh" in job:
        job["tube_flow_design_scmh"] = round(job["tube_flow_design_kgh"] / std_dens, 4)

    # Preserve v1 names as aliases so existing dashboard code still reads them
    for v1_key, v2_key in V1_ALIASES.items():
        if v2_key in job:
            job[v1_key] = job[v2_key]
    # tube_pres_out (v1) ← tube_press_out_design_barg (v2)
    if "tube_press_out_design_barg" in job:
        job["tube_pres_out"] = job["tube_press_out_design_barg"]
    print(f"  {jid:<10}  ok")

print(f"\nJobs with problems: {len(problems)}")
if DRY:
    print("--dry-run: not writing job_database.json")
else:
    with open(DB_PATH, "w", encoding="utf-8-sig") as fh:
        json.dump(db, fh, indent=4)
    print(f"Wrote {DB_PATH}")
