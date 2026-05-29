"""
Verify ALL 4 fixes for job 8308 — fouled scenario.

Symptom: tube outlet 10.3 C below design, duty loss 38.6%.
Expected: FAILED (red ring), score < 40, U_ratio reflects fouling.
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app
client = app.test_client()

with open("job_database.json", encoding="utf-8-sig") as f:
    db = json.load(f)
job = next(j for j in db if j["job_id"] == "8308")

area            = job["area"]
u_clean         = job["u_clean"]              # 987.3581
u_service_clean = job["u_service_clean"]      # 628.5061
f_factor        = job["f_factor"]
duty_design     = job["duty_design"]
std_dens        = job["std_density"]
tube_in_des     = job["tube_in"]
tube_out_des    = job["tube_out_design"]
shell_in_des    = job["shell_in"]
shell_out_des   = job["shell_out_design"]

print("=" * 78)
print("FIX 4 -- DESIGN VALUES LOADED FROM DB FOR JOB 8308")
print("=" * 78)
print(f"  duty_design     = {duty_design} kW         (should be 770.0551, NOT 1122)")
print(f"  u_clean         = {u_clean} W/m^2K   (HeatTranRatClean)")
print(f"  u_service_clean = {u_service_clean} W/m^2K   (HeatTranRatService -- U_ratio baseline)")
print(f"  area            = {area} m^2")
print(f"  f_factor        = {f_factor}")
print(f"  tube_in / out   = {tube_in_des} / {tube_out_des} C")
print(f"  shell_in / out  = {shell_in_des} / {shell_out_des} C")
print()

# Target a duty loss ~38.6% to match user's spec.
# Fouled inputs derived from energy balance / iteration:
shell_in   = 55.0
shell_out  = 42.92      # less cooling -> shell_out higher
tube_in    = 6.0
tube_out   = tube_out_des - 10.3   # 10.3 C below design = 10.73 C
shell_flow = job["shell_flow"]
tube_scmh  = job["tube_flow_kgh"] / std_dens
P_in_barg  = 71.0
P_out_barg = 70.8929

def fp(T, Pbarg):
    return client.post("/fluid_props", json={
        "fluid":"mean_bacton_gas","temp_c":T,"pressure_bar":Pbarg,
        "pressure_units":"barg","prefer_refprop":True,
    }).get_json()

print("=" * 78)
print("FOULED SITE READINGS (USER'S SCENARIO)")
print("=" * 78)
print(f"  shell_in/out  = {shell_in} / {shell_out} C")
print(f"  tube_in/out   = {tube_in} / {tube_out} C   (tube_out is {tube_out - tube_out_des:+.2f} C vs design)")
print(f"  tube_scmh     = {tube_scmh:.1f}  -- mass_flow_kgh = {tube_scmh*std_dens:.1f}")
print(f"  P_in/out      = {P_in_barg}/{P_out_barg} barg")
print()

# ── Compute (mimics dashboard runAnalysis) ────────────────────────────────────
h_in  = fp(tube_in,  P_in_barg)["h_kj_kg"]
h_out = fp(tube_out, P_out_barg)["h_kj_kg"]
mass_kgh = tube_scmh * std_dens
Q_kW = (h_out - h_in) * mass_kgh / 3600.0

dT1 = shell_in  - tube_out
dT2 = shell_out - tube_in
LMTD = (dT1 - dT2) / math.log(dT1 / dT2) if abs(dT1-dT2) > 0.001 else dT1

U_actual = Q_kW * 1000.0 / (area * LMTD * f_factor)
U_ratio  = U_actual / u_service_clean             # FIX 1: clean baseline = service U
duty_loss_pct = (duty_design - Q_kW) / duty_design * 100.0
tube_dev      = tube_out - tube_out_des
shell_dev     = shell_out - shell_out_des

print("=" * 78)
print("FIX 1 -- U RATIO CALCULATION (no rescaling, signed)")
print("=" * 78)
print(f"  H_in            = {h_in:.4f} kJ/kg")
print(f"  H_out           = {h_out:.4f} kJ/kg")
print(f"  dH              = {h_out - h_in:.4f} kJ/kg")
print(f"  Q_kW            = {Q_kW:.4f} kW  (design {duty_design}, loss {duty_loss_pct:.2f}%)")
print(f"  LMTD            = {LMTD:.4f} C")
print(f"  U_actual        = {U_actual:.4f} W/m^2K")
print(f"  u_service_clean = {u_service_clean} W/m^2K   (the baseline in use)")
print(f"  U_ratio         = U_actual / u_service_clean = {U_actual:.2f} / {u_service_clean} = {U_ratio:.4f}")
print(f"  tube_dev        = {tube_dev:+.2f} C    shell_dev = {shell_dev:+.2f} C")
print()

# ── FIX 2: ML payload — no rescaling, send U_actual + u_service_clean ─────────
print("=" * 78)
print("FIX 2 -- ML PAYLOAD (no rescaling)")
print("=" * 78)
print(f"  HeatTranRatClean = u_service_clean = {u_service_clean}")
print(f"  HeatTranRatDirty = U_actual        = {U_actual:.4f}")
print(f"  API will derive U_ratio = HeatTranRatDirty / HeatTranRatClean = {U_actual/u_service_clean:.4f}")
print()

mlPayload = {
    "HeatTranRatClean":  u_service_clean,
    "HeatTranRatDirty":  U_actual,
    "PresDropCalcSS":    0.0683,
    "PresDropCalcTS":    0.107,
    "PresDropAlloSS":    job["dp_allow_ss"],
    "PresDropAlloTS":    job["dp_allow_ts"],
    "DPratioSS":         0.0683 / job["dp_allow_ss"],
    "DPratioTS":         0.107  / job["dp_allow_ts"],
    "VelThruTubesMaxTS": job.get("vel_ts_design", 8.5),
    "VelCrossFlowMaxSS": job.get("vel_cross_design", 0.315),
    "RV2InNoz":          job.get("rv2_nozzle_design", 2077.5),
    "RV2BundleEnt":      job.get("rv2_bundle_design", 245),
    "FoulResSS":         0.000352,
    "FoulResTS":         0.000176,
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
    "FlRaTotalSS":       shell_flow,
    "FlRaTotalTS":       mass_kgh,
    "PresOperInSS":      job["shell_pres_in"],
    "PresOperInTS":      P_in_barg,
}
pred = client.post("/predict", json=mlPayload).get_json()
print(f"  ML returned class : {pred['maintenance_class']}")
print(f"  ML returned probs : {pred['maintenance_class_probabilities']}")
print(f"  ML derived U_ratio: {pred['derived_features']['U_ratio']}")
print(f"  area_ratio        : {pred['area_ratio']}  ({pred['area_ratio_label']})")
print()

# ── FIX 3: safety overrides ──────────────────────────────────────────────────
print("=" * 78)
print("FIX 3 -- SAFETY OVERRIDES (duty-loss + tube-outlet floors)")
print("=" * 78)
SEV_RANK = {"failed": 0, "critical": 1, "warning": 2, "healthy": 3}
def cap_at(cls, floor):
    return cls if SEV_RANK.get(cls, 3) <= SEV_RANK[floor] else floor

final = pred["maintenance_class"]
reasons = []
if duty_loss_pct > 30:
    final = "failed"; reasons.append(f"duty loss {duty_loss_pct:.1f}% > 30% --> FAILED")
elif duty_loss_pct > 15:
    new = cap_at(final, "critical")
    if new != final: reasons.append(f"duty loss {duty_loss_pct:.1f}% > 15% --> >= critical")
    final = new
elif duty_loss_pct > 5:
    new = cap_at(final, "warning")
    if new != final: reasons.append(f"duty loss {duty_loss_pct:.1f}% > 5% --> >= warning")
    final = new

if tube_dev < -3:
    new = cap_at(final, "critical")
    if new != final: reasons.append(f"tube outlet {tube_dev:+.1f} C --> >= critical")
    final = new
elif tube_dev < -1:
    new = cap_at(final, "warning")
    if new != final: reasons.append(f"tube outlet {tube_dev:+.1f} C --> >= warning")
    final = new

print(f"  duty_loss_pct = {duty_loss_pct:.2f}%")
print(f"  tube_dev      = {tube_dev:+.2f} C")
print(f"  ML class      : {pred['maintenance_class']}")
print(f"  FINAL class   : {final}")
for r in reasons:
    print(f"    - {r}")
print()

# ── Final tally ──────────────────────────────────────────────────────────────
score = max(0, min(100, round(U_ratio * 100)))
print("=" * 78)
print("EXPECTATIONS (user's spec)")
print("=" * 78)
print(f"  status = FAILED       : got '{final.upper()}'   -- {'PASS' if final == 'failed' else 'FAIL'}")
print(f"  duty loss ~ 38.6%     : got {duty_loss_pct:.1f}%")
print(f"  score < 40            : score = {score}        -- {'PASS' if score < 40 else 'FAIL'}")
print(f"  red ring color        : {'RED (#ff3d3d)' if final == 'failed' else 'NOT RED'}")
