"""
Remove bad_flow flag from job 8471 in job_database.json.
Run AFTER generate_and_run.ps1 + rebuild_jobdb.py have completed for 8471,
and AFTER audit_commercial.py passes 220/220·44/44·8/8.
"""
import json
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "job_database.json"

with open(DB_PATH, encoding="utf-8-sig") as f:
    db = json.load(f)

for job in db:
    if job["job_id"] == "8471":
        before_dq   = job.get("data_quality", "NOT SET")
        before_note = job.get("data_quality_note", "NOT SET")
        job.pop("data_quality", None)
        job.pop("data_quality_note", None)
        print(f"8471: removed data_quality={before_dq!r}")
        print(f"8471: removed data_quality_note={before_note!r}")
        # Confirm corrected flow values look right (expect ~3400+ kg/h, not ~0.95)
        tf = job.get("tube_flow_design_kgh", "MISSING")
        sf = job.get("shell_flow_design_kgh", "MISSING")
        print(f"8471: tube_flow_design_kgh = {tf}  (expect ~3400+)")
        print(f"8471: shell_flow_design_kgh = {sf}  (expect ~1600+)")
        if isinstance(tf, (int, float)) and tf < 10:
            print("WARNING: tube flow still looks wrong (< 10 kg/h) — do NOT save, re-check re-run")
            raise SystemExit(1)
        break
else:
    print("ERROR: job 8471 not found in database")
    raise SystemExit(1)

with open(DB_PATH, "w", encoding="utf-8-sig") as f:
    json.dump(db, f, indent=4)
print(f"Saved {DB_PATH}")
