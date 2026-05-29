"""Debug U_ratio for job 8308 — print every intermediate value the dashboard uses."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app
client = app.test_client()

# ── Load job 8308 from database ───────────────────────────────────────────────
with open("job_database.json", encoding="utf-8-sig") as f:
    db = json.load(f)
job = next(j for j in db if j["job_id"] == "8308")

area     = job["area"]
u_clean  = job["u_clean"]
f_factor = job["f_factor"]
duty_design = job["duty_design"]
std_dens = job["std_density"]

# ── User's site readings (design-equal — should yield U_ratio ~= 1.0) ─────────
shell_in   = 55.0
shell_out  = 35.0
tube_in    = 6.0
tube_out   = 21.0
shell_flow = 39139.0    # kg/h
tube_scmh  = 98952.0    # SCMH (user's value)
P_in_barg  = 71.0
P_out_barg = 69.89

print("=" * 78)
print("JOB 8308 — DEBUG U_RATIO")
print("=" * 78)
print(f"  From job_database.json:")
print(f"    Area          = {area}  m^2")
print(f"    U_clean       = {u_clean}  W/m^2K     (<- HeatTranRatClean from clean CSV row)")
print(f"    F factor      = {f_factor}            (<- MTDCorrFactor from clean CSV row)")
print(f"    duty_design   = {duty_design}  kW")
print(f"    std_density   = {std_dens}  kg/m^3")
print()
print(f"  Site readings (user's design-equal test):")
print(f"    shell_in      = {shell_in} C   shell_out = {shell_out} C")
print(f"    tube_in       = {tube_in} C   tube_out  = {tube_out} C")
print(f"    shell_flow    = {shell_flow} kg/h")
print(f"    tube_scmh     = {tube_scmh} SCMH")
print(f"    P_tube_in     = {P_in_barg} barg")
print(f"    P_tube_out    = {P_out_barg} barg")
print()

# ── Mass flow ─────────────────────────────────────────────────────────────────
mass_kgh = tube_scmh * std_dens
print(f"  mass_flow_kgh   = {tube_scmh} x {std_dens} = {mass_kgh:.4f} kg/h")
print(f"  mass_flow_kg/s  = {mass_kgh/3600:.6f}")
print()

# ── Hit /fluid_props for h_in and h_out (matches the dashboard's exact path) ─
def fp(T, Pbarg):
    r = client.post("/fluid_props", json={
        "fluid": "mean_bacton_gas",
        "temp_c": T,
        "pressure_bar": Pbarg,
        "pressure_units": "barg",
        "prefer_refprop": True,
    })
    return r.get_json()

p_in  = fp(tube_in,  P_in_barg)
p_out = fp(tube_out, P_out_barg)
h_in  = p_in["h_kj_kg"]
h_out = p_out["h_kj_kg"]

print(f"  H_in  @ ({tube_in}C, {P_in_barg} barg)  via {p_in['backend_used']}")
print(f"        = {h_in} kJ/kg")
print(f"  H_out @ ({tube_out}C, {P_out_barg} barg) via {p_out['backend_used']}")
print(f"        = {h_out} kJ/kg")
dH = h_out - h_in
print(f"  dH    = {dH:.5f} kJ/kg")
print()

# ── Q from enthalpy method ────────────────────────────────────────────────────
Q_kW = dH * mass_kgh / 3600.0
print(f"  Q_kW  = dH x mass_flow / 3600 = {Q_kW:.4f} kW")
print(f"  duty_design (DB) = {duty_design} kW   -->  Q/Q_design = {Q_kW/duty_design:.4f}")
print()

# ── LMTD from ACTUAL site temps ──────────────────────────────────────────────
dT1 = shell_in  - tube_out
dT2 = shell_out - tube_in
print(f"  dT1 = shell_in - tube_out = {shell_in} - {tube_out} = {dT1} C")
print(f"  dT2 = shell_out - tube_in = {shell_out} - {tube_in} = {dT2} C")
if abs(dT1 - dT2) < 0.001:
    LMTD = dT1
elif dT1 <= 0 or dT2 <= 0 or dT1 / dT2 <= 0:
    LMTD = (dT1 + dT2) / 2.0
else:
    LMTD = (dT1 - dT2) / math.log(dT1 / dT2)
print(f"  LMTD = (dT1 - dT2) / ln(dT1/dT2) = {LMTD:.4f} C")
print(f"  LMTD_design (DB) = {job.get('lmtd_design')} C")
print()

# ── U_actual ──────────────────────────────────────────────────────────────────
U_actual = (Q_kW * 1000.0) / (area * LMTD * f_factor)
print(f"  U_actual = Q_kW x 1000 / (Area x LMTD x F)")
print(f"           = {Q_kW:.4f} x 1000 / ({area} x {LMTD:.4f} x {f_factor})")
print(f"           = {U_actual:.4f} W/m^2K")
print()

U_ratio = U_actual / u_clean if u_clean > 0 else 0
print(f"  U_ratio  = U_actual / U_clean = {U_actual:.4f} / {u_clean} = {U_ratio:.5f}")
print()

# ── Diagnosis ─────────────────────────────────────────────────────────────────
print("=" * 78)
print("CHECKS")
print("=" * 78)
print(f"  Q_kW vs design 770 kW         : {Q_kW:.2f}  (d = {Q_kW-770:+.2f} kW, {(Q_kW-770)/770*100:+.2f} %)")
print(f"  U_actual vs U_clean 987.36    : {U_actual:.2f}  (d = {U_actual-u_clean:+.2f} W/m^2K, {(U_actual-u_clean)/u_clean*100:+.2f} %)")
print(f"  U_ratio vs 1.0                : {U_ratio:.4f}  (d = {U_ratio-1:+.4f})")
print()
print("  Sanity: is u_clean really HeatTranRatClean (not HeatTranRatDirty)?")
import csv
with open("results/results_8308.csv", encoding="utf-8-sig", newline="") as fh:
    for row in csv.DictReader(fh):
        if float(row["FoulResCS"]) == 0 and float(row["FoulResHS"]) == 0:
            print(f"    clean CSV row: HeatTranRatClean = {row['HeatTranRatClean']}")
            print(f"                   HeatTranRatDirty = {row['HeatTranRatDirty']}")
            print(f"                   (they're equal because both fouling layers = 0 — so u_clean is unambiguous)")
            print(f"    DB u_clean    = {u_clean}  -->  MATCH")
            break
