"""Run 8308 with the EXACT design inputs from job_database.json + check CSV columns."""
import csv, json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app
client = app.test_client()

with open("job_database.json", encoding="utf-8-sig") as f:
    db = json.load(f)
job = next(j for j in db if j["job_id"] == "8308")

# True design from DB
shell_in   = job["shell_in"]                # 55
shell_out  = job["shell_out_design"]        # 34.9902
tube_in    = job["tube_in"]                 # 5.9995
tube_out   = job["tube_out_design"]         # 21.0341
shell_flow = job["shell_flow"]
tube_flow_kgh_design = job["tube_flow_kgh"] # 66247.99 (TRUE design mass flow)
P_in_barg  = job["tube_pres_in"]            # 71.0
P_out_barg = job["tube_pres_out"]           # 70.8929
std_dens   = job["std_density"]
tube_scmh_design = tube_flow_kgh_design / std_dens  # ~90,952

area     = job["area"]
u_clean  = job["u_clean"]                   # 987.3581 (HeatTranRatClean from clean row)
f_factor = job["f_factor"]                  # 1.002404
duty_design = job["duty_design"]            # 770.0551

def fp(T, Pbarg):
    return client.post("/fluid_props", json={
        "fluid":"mean_bacton_gas","temp_c":T,"pressure_bar":Pbarg,
        "pressure_units":"barg","prefer_refprop":True,
    }).get_json()

print("=" * 78)
print("JOB 8308 -- using EXACT design inputs from DB")
print("=" * 78)
print(f"  shell_in/out = {shell_in}/{shell_out}  tube_in/out = {tube_in}/{tube_out}")
print(f"  tube_flow    = {tube_flow_kgh_design} kg/h   (= {tube_scmh_design:.1f} SCMH at std_density {std_dens})")
print(f"  P_in/out     = {P_in_barg}/{P_out_barg} barg")
print()

p_in  = fp(tube_in,  P_in_barg)
p_out = fp(tube_out, P_out_barg)
h_in, h_out = p_in["h_kj_kg"], p_out["h_kj_kg"]
dH = h_out - h_in
Q_kW = dH * tube_flow_kgh_design / 3600
print(f"  H_in  = {h_in} kJ/kg   H_out = {h_out} kJ/kg   dH = {dH:.5f} kJ/kg")
print(f"  Q_kW  = {Q_kW:.4f}    (design = {duty_design} kW, error = {(Q_kW-duty_design)/duty_design*100:+.3f}%)")

dT1 = shell_in - tube_out
dT2 = shell_out - tube_in
LMTD = (dT1 - dT2) / math.log(dT1 / dT2) if abs(dT1-dT2) > 0.001 else dT1
print(f"  LMTD = {LMTD:.4f}  (design = {job['lmtd_design']})")

U_actual = Q_kW * 1000 / (area * LMTD * f_factor)
print(f"  U_actual = Q*1000 / (A*LMTD*F) = {U_actual:.4f} W/m^2K")
print()

# ── Now inspect the CSV columns at the clean row ─────────────────────────────
print("CSV clean-row columns for 8308:")
with open("results/results_8308.csv", encoding="utf-8-sig", newline="") as fh:
    for row in csv.DictReader(fh):
        if float(row["FoulResCS"]) == 0 and float(row["FoulResHS"]) == 0:
            print(f"    HeatTranRatClean   = {row['HeatTranRatClean']}    (theoretical clean U)")
            print(f"    HeatTranRatDirty   = {row['HeatTranRatDirty']}    (theoretical fouled U)")
            print(f"    HeatTranRatService = {row['HeatTranRatService']}    (service U  = U_clean / AreaRatio)")
            print(f"    AreaRatioClean     = {row['AreaRatioClean']}     (excess area ratio when clean)")
            hr_clean   = float(row["HeatTranRatClean"])
            hr_service = float(row["HeatTranRatService"])
            ar_clean   = float(row["AreaRatioClean"])
            break

print()
print(f"  Identity check: U_clean / AreaRatioClean = {hr_clean}/{ar_clean} = {hr_clean/ar_clean:.4f}")
print(f"                                                       vs HeatTranRatService = {hr_service}")
print()

print("U_ratio under each candidate baseline:")
for label, baseline in [
    ("HeatTranRatClean   (987)", hr_clean),
    ("HeatTranRatService (628)", hr_service),
]:
    print(f"    U_actual / {label:<28} = {U_actual:.3f} / {baseline:.3f} = {U_actual/baseline:.4f}")
