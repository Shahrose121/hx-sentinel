"""
Verify FIX 1+2+3 with user's exact fouled scenario:
  shell_out = 40 (design 35), tube_out = 16 (design 21)
  Expected: CRITICAL or FAILED, ring < 70.

Also confirms FIX 2 (dP from in/out pressures) and FIX 3
(tube velocity + RhoV² from REFPROP density + geometry).
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app
client = app.test_client()

with open("job_database.json", encoding="utf-8-sig") as f:
    db = json.load(f)
job = next(j for j in db if j["job_id"] == "8308")

area            = job["area"]
u_service_clean = job["u_service_clean"]
f_factor        = job["f_factor"]
duty_design     = job["duty_design"]
std_dens        = job["std_density"]
tube_out_design = job["tube_out_design"]
shell_out_design = job["shell_out_design"]
tube_id_mm      = job["tube_id"]
tube_count      = job["tube_num"]
tube_pass_num   = job["tube_pass"]

# User's fouled scenario
shell_in  = 55.0
shell_out = 40.0          # design 35, +5 deviation
tube_in   = 6.0
tube_out  = 16.0          # design 21, -5 deviation

# Pressures: use design (the user didn't specify, so default to design barg)
P_shell_in_barg  = 4.0
P_shell_out_barg = 3.99939
P_tube_in_barg   = 71.0
P_tube_out_barg  = 70.8929

tube_scmh = job["tube_flow_kgh"] / std_dens   # 90952.5

# --- Mimic dashboard pipeline ---
def fp(T, Pbarg):
    return client.post("/fluid_props", json={
        "fluid":"mean_bacton_gas","temp_c":T,"pressure_bar":Pbarg,
        "pressure_units":"barg","prefer_refprop":True,
    }).get_json()

fp_in  = fp(tube_in,  P_tube_in_barg)
fp_out = fp(tube_out, P_tube_out_barg)
h_in, h_out = fp_in["h_kj_kg"], fp_out["h_kj_kg"]
mass_kgh = tube_scmh * std_dens
mass_kgs = mass_kgh / 3600.0
Q_kW = (h_out - h_in) * mass_kgh / 3600.0

dT1 = shell_in  - tube_out
dT2 = shell_out - tube_in
LMTD = (dT1 - dT2) / math.log(dT1 / dT2) if abs(dT1-dT2) > 0.001 else dT1
U_actual = Q_kW * 1000.0 / (area * LMTD * f_factor)
U_ratio  = U_actual / u_service_clean
score    = round(max(0, min(100, U_ratio * 100)))

duty_loss_pct = (duty_design - Q_kW) / duty_design * 100.0
tube_dev      = tube_out - tube_out_design
shell_dev     = shell_out - shell_out_design

# FIX 2: dP from pressures
dpSS = max(0, P_shell_in_barg - P_shell_out_barg)
dpTS = max(0, P_tube_in_barg  - P_tube_out_barg)

# FIX 3: tube velocity + RhoV²
tube_density   = (fp_in["density_kg_m3"] + fp_out["density_kg_m3"]) / 2.0
tube_id_m      = tube_id_mm / 1000.0
tube_flow_area = (math.pi / 4) * tube_id_m**2 * (tube_count / tube_pass_num)
tube_velocity  = mass_kgs / (tube_density * tube_flow_area)
rv2            = tube_density * tube_velocity**2

print("=" * 72)
print("JOB 8308 -- FOULED (shell out 40 C, tube out 16 C)")
print("=" * 72)

print("\n[FIX 1] U_ratio")
print(f"  u_service_clean (from DB)     : {u_service_clean} W/m^2K")
print(f"  U_actual                      : {U_actual:.4f} W/m^2K")
print(f"  U_ratio = U_actual / baseline : {U_actual:.2f} / {u_service_clean} = {U_ratio:.4f}")
print(f"  Ring score = U_ratio * 100    : {score}")
print(f"  U degradation                 : {(1-U_ratio)*100:.2f}%")
print(f"  Q_kW                          : {Q_kW:.2f}   duty_loss = {duty_loss_pct:.2f}%")
print(f"  shell_dev / tube_dev          : {shell_dev:+.2f} C / {tube_dev:+.2f} C")

print("\n[FIX 2] Pressure drops (auto-computed)")
print(f"  dP_shell = {P_shell_in_barg} - {P_shell_out_barg} = {dpSS:.5f} bar")
print(f"  dP_tube  = {P_tube_in_barg}  - {P_tube_out_barg}  = {dpTS:.4f} bar")

print("\n[FIX 3] Tube velocity + RhoV^2 (auto-computed)")
print(f"  density (mean tube, REFPROP)  : {tube_density:.4f} kg/m^3")
print(f"  geometry  ID = {tube_id_mm} mm, N_tubes = {tube_count}, passes = {tube_pass_num}")
print(f"  flow area = pi/4 * ({tube_id_mm/1000:.6f})^2 * ({tube_count}/{tube_pass_num})")
print(f"            = {tube_flow_area:.6f} m^2")
print(f"  mass flow = {tube_scmh:.1f} SCMH x {std_dens} / 3600 = {mass_kgs:.4f} kg/s")
print(f"  velocity  = {mass_kgs:.4f} / ({tube_density:.2f} x {tube_flow_area:.5f}) = {tube_velocity:.4f} m/s")
print(f"  RhoV^2    = {tube_density:.2f} x {tube_velocity:.4f}^2 = {rv2:.1f} kg/m·s^2")
print(f"  (design vel_ts_design = {job.get('vel_ts_design')}, rv2_nozzle_design = {job.get('rv2_nozzle_design')})")

# ML payload
mlPayload = {
    "HeatTranRatClean":  u_service_clean,
    "HeatTranRatDirty":  U_actual,
    "PresDropCalcSS":    dpSS,
    "PresDropCalcTS":    dpTS,
    "PresDropAlloSS":    job["dp_allow_ss"],
    "PresDropAlloTS":    job["dp_allow_ts"],
    "DPratioSS":         dpSS / job["dp_allow_ss"],
    "DPratioTS":         dpTS / job["dp_allow_ts"],
    "VelThruTubesMaxTS": tube_velocity,
    "VelCrossFlowMaxSS": job.get("vel_cross_design", 0.315),
    "RV2InNoz":          rv2,
    "RV2BundleEnt":      job.get("rv2_bundle_design", 245),
    "FoulResSS":         0.0, "FoulResTS":         0.0,
    "LMTD":              LMTD, "MTDCorrFactor":     f_factor,
    "TempInSS":          shell_in, "TempInTS":          tube_in,
    "FilmCoefSS":        job["film_coef_ss"], "FilmCoefTS":        job["film_coef_ts"],
    "TubeNum":           tube_count, "TubeOD":            job["tube_od"],
    "TubeID":            job["tube_id"], "TubeLng":           job["tube_lng"],
    "ShlID":             job["shl_id"], "BafNum":            job["baf_num"],
    "BafSpcCC":          job["baf_spc"], "BafCutPerc":        job["baf_cut"],
    "TubePassNum":       tube_pass_num, "Area":              area,
    "FlRaTotalSS":       job["shell_flow"], "FlRaTotalTS":       mass_kgh,
    "PresOperInSS":      P_shell_in_barg, "PresOperInTS":      P_tube_in_barg,
}
pred = client.post("/predict", json=mlPayload).get_json()
ml_class = pred["maintenance_class"]

# Safety overrides (must match dashboard)
SEV = {"healthy":0, "warning":1, "critical":2, "failed":3}
worse_of = lambda a, b: a if SEV[a] >= SEV[b] else b
final = ml_class
reasons = []
if duty_loss_pct > 30:
    if final != "failed": reasons.append(f"duty loss {duty_loss_pct:.1f}% > 30% -> FAILED")
    final = "failed"
elif duty_loss_pct > 15:
    if final != "critical": reasons.append(f"duty loss {duty_loss_pct:.1f}% in (15,30] -> CRITICAL")
    final = "critical"
elif duty_loss_pct > 5:
    if final != "warning": reasons.append(f"duty loss {duty_loss_pct:.1f}% in (5,15] -> WARNING")
    final = "warning"
if tube_dev < -3:
    new = worse_of(final, "critical")
    if new != final: reasons.append(f"tube outlet {tube_dev:+.1f} C -> >= CRITICAL")
    final = new
elif tube_dev < -1:
    new = worse_of(final, "warning")
    if new != final: reasons.append(f"tube outlet {tube_dev:+.1f} C -> >= WARNING")
    final = new

print()
print("=" * 72)
print(f"  ML class            : {ml_class}")
print(f"  FINAL class         : {final}")
for r in reasons: print(f"    - {r}")
print()
print("EXPECTATIONS")
print(f"  Status = CRITICAL or FAILED : {final.upper()}      -- {'PASS' if final in ('critical','failed') else 'FAIL'}")
print(f"  Ring score < 70             : {score}              -- {'PASS' if score < 70 else 'FAIL'}")
print(f"  dP auto-computed (FIX 2)    : ss={dpSS:.5f}, ts={dpTS:.4f}")
print(f"  Velocity auto-computed      : {tube_velocity:.3f} m/s (FIX 3)")
print(f"  RhoV^2 auto-computed        : {rv2:.0f} kg/m·s^2  (FIX 3)")
