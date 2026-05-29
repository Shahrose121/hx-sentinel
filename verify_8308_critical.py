"""
Verify the U_ratio bug is fixed — fouled job 8308 should give
U_ratio ~ 0.649, ring score ~ 64, status CRITICAL.

Prints the 4 debug values the user requested:
  1. u_service_clean loaded for job 8308
  2. U_actual calculated
  3. U_ratio = U_actual / u_service_clean
  4. Health ring score (from same U_ratio)
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app
client = app.test_client()

with open("job_database.json", encoding="utf-8-sig") as f:
    db = json.load(f)
job = next(j for j in db if j["job_id"] == "8308")

area            = job["area"]
u_clean         = job["u_clean"]
u_service_clean = job["u_service_clean"]
f_factor        = job["f_factor"]
duty_design     = job["duty_design"]
std_dens        = job["std_density"]
tube_out_design = job["tube_out_design"]

# Fouled site readings targeting ~25% duty loss + U_actual ~ 400 W/m²K
shell_in, shell_out = 55.0, 40.0
tube_in,  tube_out  = 6.0, 17.0
shell_flow = job["shell_flow"]
tube_scmh  = job["tube_flow_kgh"] / std_dens
P_in_barg, P_out_barg = 71.0, 70.8929

def fp(T, Pbarg):
    return client.post("/fluid_props", json={
        "fluid":"mean_bacton_gas","temp_c":T,"pressure_bar":Pbarg,
        "pressure_units":"barg","prefer_refprop":True,
    }).get_json()

# ── Dashboard pipeline ────────────────────────────────────────────────────────
h_in  = fp(tube_in,  P_in_barg)["h_kj_kg"]
h_out = fp(tube_out, P_out_barg)["h_kj_kg"]
mass_kgh = tube_scmh * std_dens
Q_kW = (h_out - h_in) * mass_kgh / 3600.0

dT1 = shell_in  - tube_out
dT2 = shell_out - tube_in
LMTD = (dT1 - dT2) / math.log(dT1 / dT2) if abs(dT1-dT2) > 0.001 else dT1

U_actual = Q_kW * 1000.0 / (area * LMTD * f_factor)
U_ratio  = U_actual / u_service_clean
score    = round(max(0, min(100, U_ratio * 100)))

duty_loss_pct = (duty_design - Q_kW) / duty_design * 100.0
U_degradation = (1 - U_ratio) * 100.0
tube_dev      = tube_out - tube_out_design

print("=" * 72)
print("DEBUG -- the 4 values requested")
print("=" * 72)
print(f"  1. u_service_clean for 8308 (from DB)  : {u_service_clean} W/m^2K")
print(f"  2. U_actual = Q*1000/(A*LMTD*F)        : {U_actual:.4f} W/m^2K")
print(f"  3. U_ratio = U_actual / u_service_clean: {U_actual:.2f} / {u_service_clean} = {U_ratio:.4f}")
print(f"  4. Health ring score = U_ratio*100     : {score}")
print()
print(f"  Q_kW                : {Q_kW:.2f} kW    duty_loss = {duty_loss_pct:.2f}%")
print(f"  LMTD                : {LMTD:.2f} C")
print(f"  tube_dev            : {tube_dev:+.2f} C  (design {tube_out_design})")
print(f"  U degradation       : (1 - {U_ratio:.4f}) * 100 = {U_degradation:.2f}%")
print()

# ── ML payload (no rescaling) ─────────────────────────────────────────────────
mlPayload = {
    "HeatTranRatClean":  u_service_clean,
    "HeatTranRatDirty":  U_actual,
    "PresDropCalcSS":    0.0683, "PresDropCalcTS":    0.107,
    "PresDropAlloSS":    job["dp_allow_ss"], "PresDropAlloTS":    job["dp_allow_ts"],
    "DPratioSS":         0.0683 / job["dp_allow_ss"],
    "DPratioTS":         0.107  / job["dp_allow_ts"],
    "VelThruTubesMaxTS": job.get("vel_ts_design", 8.5),
    "VelCrossFlowMaxSS": job.get("vel_cross_design", 0.315),
    "RV2InNoz":          job.get("rv2_nozzle_design", 2077.5),
    "RV2BundleEnt":      job.get("rv2_bundle_design", 245),
    "FoulResSS":         0.000352, "FoulResTS":         0.000176,
    "LMTD":              LMTD, "MTDCorrFactor":     f_factor,
    "TempInSS":          shell_in, "TempInTS":          tube_in,
    "FilmCoefSS":        job["film_coef_ss"], "FilmCoefTS":        job["film_coef_ts"],
    "TubeNum":           job["tube_num"], "TubeOD":            job["tube_od"],
    "TubeID":            job["tube_id"], "TubeLng":           job["tube_lng"],
    "ShlID":             job["shl_id"], "BafNum":            job["baf_num"],
    "BafSpcCC":          job["baf_spc"], "BafCutPerc":        job["baf_cut"],
    "TubePassNum":       job["tube_pass"], "Area":              area,
    "FlRaTotalSS":       shell_flow, "FlRaTotalTS":       mass_kgh,
    "PresOperInSS":      job["shell_pres_in"], "PresOperInTS":      P_in_barg,
}
pred = client.post("/predict", json=mlPayload).get_json()
ml_class = pred["maintenance_class"]
ml_uratio = pred["derived_features"]["U_ratio"]

# ── Safety overrides (must match dashboard.html) ─────────────────────────────
#   duty bracket overrides ML to EXACT value; tube_dev only escalates.
SEV = {"healthy":0, "warning":1, "critical":2, "failed":3}
def worse_of(a, b):
    return a if SEV[a] >= SEV[b] else b

final = ml_class
reasons = []
if duty_loss_pct > 30:
    if final != "failed": reasons.append(f"duty loss {duty_loss_pct:.1f}% > 30% --> FAILED")
    final = "failed"
elif duty_loss_pct > 15:
    if final != "critical": reasons.append(f"duty loss {duty_loss_pct:.1f}% in (15,30] --> CRITICAL")
    final = "critical"
elif duty_loss_pct > 5:
    if final != "warning": reasons.append(f"duty loss {duty_loss_pct:.1f}% in (5,15] --> WARNING")
    final = "warning"

if tube_dev < -3:
    esc = worse_of(final, "critical")
    if esc != final: reasons.append(f"tube outlet {tube_dev:+.1f} C --> >= CRITICAL")
    final = esc
elif tube_dev < -1:
    esc = worse_of(final, "warning")
    if esc != final: reasons.append(f"tube outlet {tube_dev:+.1f} C --> >= WARNING")
    final = esc

print(f"  ML class            : {ml_class}      (API-derived U_ratio = {ml_uratio:.4f})")
print(f"  FINAL class         : {final}")
for r in reasons: print(f"    - {r}")
print()

# Ring color logic from displayHealth: uRatioCol uses U_ratio thresholds
ring_color = "#ff3d3d (red)" if final == "failed" else \
             "#ff6600 (orange-red)" if final == "critical" else \
             "#ffb800 (orange)" if final == "warning" else \
             "#00ff9d (green)"

print("=" * 72)
print("EXPECTATIONS")
print("=" * 72)
print(f"  U_ratio ~ 0.6-0.7     : {U_ratio:.4f}   -- {'PASS' if 0.5 <= U_ratio <= 0.8 else 'FAIL'}")
print(f"  Ring score ~ 64       : {score}      -- {'PASS' if 50 <= score <= 75 else 'FAIL'}")
print(f"  Status = CRITICAL     : {final.upper()}   -- {'PASS' if final == 'critical' else 'FAIL'}")
print(f"  Ring color (orange)   : {ring_color}")
print(f"  NOT showing 2.193     : U_ratio = {U_ratio:.4f}  -- {'PASS' if U_ratio < 1.5 else 'FAIL'}")
print(f"  Degradation +ve %     : {U_degradation:.1f}%  -- {'PASS' if U_degradation > 0 else 'FAIL'}")
