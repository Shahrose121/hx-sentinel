"""
Final verification — mimic the dashboard's entire pipeline for job 8308 at
design conditions and confirm:
  Q ~= 770 kW
  U_actual ~= u_service_clean (628.5)
  U_ratio ~= 1.0
  ML classification = healthy
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app
client = app.test_client()

with open("job_database.json", encoding="utf-8-sig") as f:
    db = json.load(f)
job = next(j for j in db if j["job_id"] == "8308")

area            = job["area"]
u_clean         = job["u_clean"]            # 987.3581 -- HeatTranRatClean
u_service_clean = job["u_service_clean"]    # 628.5061 -- HeatTranRatService at clean
f_factor        = job["f_factor"]
duty_design     = job["duty_design"]
std_dens        = job["std_density"]

# DESIGN test inputs (true design, not the user's typed values)
shell_in  = 55.0
shell_out = 35.0
tube_in   = 6.0
tube_out  = 21.0
shell_flow_kgh = 39139.0
tube_scmh = job["tube_flow_kgh"] / std_dens   # 90952.5 (true design SCMH)
P_in_barg  = 71.0
P_out_barg = 70.8929

def fp(T, Pbarg):
    return client.post("/fluid_props", json={
        "fluid":"mean_bacton_gas","temp_c":T,"pressure_bar":Pbarg,
        "pressure_units":"barg","prefer_refprop":True,
    }).get_json()

# ── Pipeline (matches dashboard.html runAnalysis) ─────────────────────────────
h_in  = fp(tube_in,  P_in_barg)["h_kj_kg"]
h_out = fp(tube_out, P_out_barg)["h_kj_kg"]
mass_kgh = tube_scmh * std_dens
Q_kW = (h_out - h_in) * mass_kgh / 3600.0

dT1 = shell_in - tube_out
dT2 = shell_out - tube_in
LMTD = (dT1 - dT2) / math.log(dT1 / dT2) if abs(dT1-dT2) > 0.001 else dT1

U_actual = Q_kW * 1000.0 / (area * LMTD * f_factor)
U_ratio  = U_actual / u_service_clean      # NEW: uses HeatTranRatService baseline
heatTranRatDirty_est = u_clean * U_ratio   # NEW: scaled back to theoretical-clean basis

print(f"Q_kW                        : {Q_kW:.4f}   (design {duty_design}, dev {(Q_kW-duty_design)/duty_design*100:+.3f}%)")
print(f"LMTD                        : {LMTD:.4f}")
print(f"U_actual = Q*1000/(A*LMTD*F): {U_actual:.4f} W/m^2K")
print(f"U_clean         (DB)        : {u_clean}    (HeatTranRatClean)")
print(f"U_service_clean (DB, NEW)   : {u_service_clean}  (HeatTranRatService)")
print(f"U_ratio = U_actual / U_service_clean = {U_ratio:.5f}")
print(f"HeatTranRatDirty_est = U_clean * U_ratio = {heatTranRatDirty_est:.3f} (sent to ML)")

# ── ML payload (matching dashboard) ───────────────────────────────────────────
mlPayload = {
    "HeatTranRatClean":  u_clean,
    "HeatTranRatDirty":  heatTranRatDirty_est,
    "PresDropCalcSS":    0.0683,
    "PresDropCalcTS":    0.107,
    "PresDropAlloSS":    job["dp_allow_ss"],
    "PresDropAlloTS":    job["dp_allow_ts"],
    "DPratioSS":         0.0683 / job["dp_allow_ss"],
    "DPratioTS":         0.107  / job["dp_allow_ts"],
    "VelThruTubesMaxTS": job.get("vel_ts_design", 8.5),
    "VelCrossFlowMaxSS": job.get("vel_cross_design", 0.315),
    "RV2InNoz":          job.get("rv2_nozzle_design", 2077.5),
    "FoulResSS":         0.0,
    "FoulResTS":         0.0,
    "LMTD":              LMTD,
    "MTDCorrFactor":     f_factor,
    "TempInSS":          shell_in,
    "TempInTS":          tube_in,
    "FilmCoefSS":        job["film_coef_ss"],
    "FilmCoefTS":        job["film_coef_ts"],
    "TubeNum":           job["tube_num"],
    "TubeOD":            job["tube_od"],
    "TubeID":            job["tube_id"],
    "TubeLng":           job["tube_lng"],
    "ShlID":             job["shl_id"],
    "BafNum":            job["baf_num"],
    "BafSpcCC":          job["baf_spc"],
    "BafCutPerc":        job["baf_cut"],
    "TubePassNum":       job["tube_pass"],
    "Area":              area,
    "FlRaTotalSS":       shell_flow_kgh,
    "FlRaTotalTS":       mass_kgh,
    "PresOperInSS":      job["shell_pres_in"],
    "PresOperInTS":      P_in_barg,
    "RV2BundleEnt":      job.get("rv2_bundle_design", 245),
}

r = client.post("/predict", json=mlPayload)
pred = r.get_json()
print()
print(f"ML classification           : {pred.get('maintenance_class')}")
print(f"ML probabilities            : {pred.get('maintenance_class_probabilities')}")
print(f"Area ratio (regressor)      : {pred.get('area_ratio')}  -- label {pred.get('area_ratio_label')}")
print()
print("EXPECTATIONS:")
print(f"  Q ~= 770 kW            : Q = {Q_kW:.2f}  -- {'PASS' if abs(Q_kW-770) < 10 else 'FAIL'}")
print(f"  U_actual ~= 628.5      : U = {U_actual:.2f}  -- {'PASS' if abs(U_actual-u_service_clean) < 10 else 'FAIL'}")
print(f"  U_ratio ~= 1.0         : R = {U_ratio:.4f}  -- {'PASS' if abs(U_ratio-1.0) < 0.02 else 'FAIL'}")
print(f"  Status = healthy       : C = {pred.get('maintenance_class')}  -- {'PASS' if pred.get('maintenance_class') == 'healthy' else 'FAIL'}")
