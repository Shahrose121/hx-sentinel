"""Find every job whose DB tube_pres_in / tube_pres_out / shell_pres_in
disagrees with the CSV clean-row PresOperInTS / PresOperInSS / PresDropCalcTS."""
import csv, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
db = json.load(open(ROOT/"job_database.json", encoding="utf-8-sig"))


def clean_row(jid):
    for p in (ROOT/"results"/f"results_{jid}.csv", ROOT/f"results_{jid}.csv"):
        if p.exists():
            with open(p, encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    if float(row.get("FoulResCS","1"))==0 and float(row.get("FoulResHS","1"))==0:
                        return row
    return None


def fnum(s):
    try: return float(s)
    except: return None


def near(a,b,tol=0.01):
    if a is None or b is None: return a==b
    return abs(a-b) <= tol*max(1, abs(a), abs(b))


print(f"{'JOB':<10} {'db tubeP_in':>11} {'csv P_TS':>10} {'db tubeP_out':>13} {'csv P_TS-dP':>13} {'db shellP_in':>13} {'csv P_SS':>9}  fix?")
print("-"*100)
need_fix = []
for j in db:
    jid = j["job_id"]
    row = clean_row(jid)
    if not row:
        print(f"{jid:<10} -- no CSV --")
        continue
    csv_tin = fnum(row.get("PresOperInTS"))
    csv_ssn = fnum(row.get("PresOperInSS"))
    csv_dpt = fnum(row.get("PresDropCalcTS"))
    csv_dps = fnum(row.get("PresDropCalcSS"))
    db_tin  = fnum(j.get("tube_pres_in"))
    db_tout = fnum(j.get("tube_pres_out"))
    db_ssn  = fnum(j.get("shell_pres_in"))

    csv_tout = (csv_tin - csv_dpt) if (csv_tin is not None and csv_dpt is not None) else None

    bad = (not near(db_tin, csv_tin, 0.05)
        or not near(db_tout, csv_tout, 0.05)
        or not near(db_ssn, csv_ssn, 0.05))
    flag = "FIX" if bad else ""
    if bad: need_fix.append((jid, db_tin, csv_tin, db_tout, csv_tout, db_ssn, csv_ssn))
    print(f"{jid:<10} {db_tin!s:>11} {csv_tin!s:>10} {db_tout!s:>13} {csv_tout if csv_tout is None else round(csv_tout,4)!s:>13} {db_ssn!s:>13} {csv_ssn!s:>9}  {flag}")

print(f"\nTotal jobs needing pressure fixes: {len(need_fix)}")
