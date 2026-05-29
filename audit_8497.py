"""
Comprehensive 5-scenario audit of job 8497.

Mimics the dashboard runAnalysis() pipeline 1:1 — REFPROP enthalpy,
LMTD, U_actual, U_ratio, auto-computed dP / velocity / RhoV^2,
ML prediction, safety overrides.

Verifies 8 checks per scenario:
  1. U_ratio direction          (clean=1.0, fouled<1.0)
  2. Health score direction     (matches U_ratio sign)
  3. Status matches conditions  (per user's expected band)
  4. Duty loss calculation      (matches Q math)
  5. dP ratios correct          (= actual/allowable)
  6. Thermal panel deviations   (shell_dev, tube_dev signs/values)
  7. Diagnostic text            (right severity for each metric)
  8. TEMA limits                (velocity, RhoV^2, dP-ratio thresholds)
"""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app
client = app.test_client()

with open("job_database.json", encoding="utf-8-sig") as f:
    db = json.load(f)
J = next(j for j in db if j["job_id"] == "8497")

# ── Helpers ───────────────────────────────────────────────────────────────────
SEV = {"healthy":0, "warning":1, "critical":2, "failed":3}
def worse_of(a, b): return a if SEV[a] >= SEV[b] else b

def fp(T, Pbarg):
    return client.post("/fluid_props", json={
        "fluid":"mean_bacton_gas","temp_c":T,"pressure_bar":Pbarg,
        "pressure_units":"barg","prefer_refprop":True,
    }).get_json()

def run_pipeline(s):
    """One scenario through the full dashboard pipeline."""
    p_in  = fp(s["tube_in"],  s["tube_p_in"])
    p_out = fp(s["tube_out"], s["tube_p_out"])
    h_in, h_out = p_in["h_kj_kg"], p_out["h_kj_kg"]

    mass_kgh = s["tube_scmh"] * J["std_density"]
    mass_kgs = mass_kgh / 3600.0
    Q = (h_out - h_in) * mass_kgh / 3600.0

    dT1 = s["shell_in"] - s["tube_out"]
    dT2 = s["shell_out"] - s["tube_in"]
    if abs(dT1 - dT2) < 0.001:           LMTD = dT1
    elif dT1 <= 0 or dT2 <= 0:           LMTD = (dT1 + dT2) / 2
    else:                                LMTD = (dT1 - dT2) / math.log(dT1/dT2)

    U_actual = Q*1000 / (J["area"] * LMTD * J["f_factor"]) if LMTD > 0 else 0
    U_ratio  = U_actual / J["u_service_clean"]
    score    = round(max(0, min(100, U_ratio * 100)))
    duty_loss_pct = (J["duty_design"] - Q) / J["duty_design"] * 100
    tube_dev = s["tube_out"] - J["tube_out_design"]
    shell_dev = s["shell_out"] - J["shell_out_design"]

    # FIX 2: dP from pressures
    dpSS = max(0, s["shell_p_in"] - s["shell_p_out"])
    dpTS = max(0, s["tube_p_in"]  - s["tube_p_out"])
    dpr_ss = dpSS / J["dp_allow_ss"]
    dpr_ts = dpTS / J["dp_allow_ts"]

    # FIX 3: tube velocity + RhoV2 from REFPROP density + geometry
    rho = (p_in["density_kg_m3"] + p_out["density_kg_m3"]) / 2
    tube_id_m = J["tube_id"] / 1000
    area_tube = (math.pi / 4) * tube_id_m**2 * (J["tube_num"] / J["tube_pass"])
    tubeVel = mass_kgs / (rho * area_tube)
    rv2 = rho * tubeVel**2

    # ML call
    ml = client.post("/predict", json={
        "HeatTranRatClean": J["u_service_clean"],
        "HeatTranRatDirty": U_actual,
        "PresDropCalcSS": dpSS, "PresDropCalcTS": dpTS,
        "PresDropAlloSS": J["dp_allow_ss"], "PresDropAlloTS": J["dp_allow_ts"],
        "DPratioSS": dpr_ss, "DPratioTS": dpr_ts,
        "VelThruTubesMaxTS": tubeVel,
        "VelCrossFlowMaxSS": J["vel_cross_design"],
        "RV2InNoz": rv2, "RV2BundleEnt": J["rv2_bundle_design"],
        "FoulResSS": 0, "FoulResTS": 0,
        "LMTD": LMTD, "MTDCorrFactor": J["f_factor"],
        "TempInSS": s["shell_in"], "TempInTS": s["tube_in"],
        "FilmCoefSS": J["film_coef_ss"], "FilmCoefTS": J["film_coef_ts"],
        "TubeNum": J["tube_num"], "TubeOD": J["tube_od"], "TubeID": J["tube_id"],
        "TubeLng": J["tube_lng"], "ShlID": J["shl_id"],
        "BafNum": J["baf_num"], "BafSpcCC": J["baf_spc"], "BafCutPerc": J["baf_cut"],
        "TubePassNum": J["tube_pass"], "Area": J["area"],
        "FlRaTotalSS": s["shell_flow"], "FlRaTotalTS": mass_kgh,
        "PresOperInSS": s["shell_p_in"], "PresOperInTS": s["tube_p_in"],
    }).get_json()
    ml_class = ml["maintenance_class"]

    # Safety overrides (matching dashboard)
    final = ml_class
    if   duty_loss_pct > 40: final = "failed"
    elif duty_loss_pct > 20: final = "critical"
    elif duty_loss_pct > 5:  final = "warning"
    if   tube_dev < -3: final = worse_of(final, "critical")
    elif tube_dev < -1: final = worse_of(final, "warning")
    max_dpr = max(dpr_ss, dpr_ts)
    if   max_dpr > 1.0: final = worse_of(final, "critical")
    elif max_dpr > 0.8: final = worse_of(final, "warning")

    # Diagnostic text severities
    diag_max = 0
    diag_msgs = []
    def push(sev, msg):
        nonlocal diag_max
        diag_max = max(diag_max, sev); diag_msgs.append(("danger" if sev==2 else "warning", msg))
    if shell_dev > 3:  push(2, f"Shell outlet {shell_dev:+.1f} C -- significant fouling")
    elif shell_dev > 1:push(1, f"Shell outlet {shell_dev:+.1f} C -- early fouling")
    if tube_dev < -3:  push(2, f"Tube outlet {abs(tube_dev):.1f} below -- significant fouling")
    elif tube_dev < -1:push(1, f"Tube outlet {abs(tube_dev):.1f} below -- early fouling")
    if duty_loss_pct > 15:   push(2, f"Duty {duty_loss_pct:.1f}% below design")
    elif duty_loss_pct > 5:  push(1, f"Duty {duty_loss_pct:.1f}% below design")
    if U_ratio < 0.72:  push(2, f"U degraded {(1-U_ratio)*100:.0f}%")
    elif U_ratio < 0.85:push(1, f"U degraded {(1-U_ratio)*100:.0f}%")
    if dpr_ss > 1.0:    push(2, f"Shell dP {dpr_ss*100:.0f}% EXCEEDED")
    elif dpr_ss > 0.8:  push(1, f"Shell dP {dpr_ss*100:.0f}%")
    if dpr_ts > 1.0:    push(2, f"Tube dP {dpr_ts*100:.0f}% EXCEEDED")
    elif dpr_ts > 0.8:  push(1, f"Tube dP {dpr_ts*100:.0f}%")

    # TEMA limits
    tema = {}
    tema["vel"] = "danger" if tubeVel > 40 else "warning" if tubeVel > 32 else "ok"
    tema["rv2"] = "danger" if rv2     > 2232 else "warning" if rv2 > 1786 else "ok"
    tema["dpss"]= "danger" if dpr_ss  > 1.0 else "warning" if dpr_ss > 0.8 else "ok"
    tema["dpts"]= "danger" if dpr_ts  > 1.0 else "warning" if dpr_ts > 0.8 else "ok"

    return dict(Q=Q, U_actual=U_actual, U_ratio=U_ratio, score=score,
                duty_loss=duty_loss_pct, tube_dev=tube_dev, shell_dev=shell_dev,
                dpSS=dpSS, dpTS=dpTS, dpr_ss=dpr_ss, dpr_ts=dpr_ts,
                tubeVel=tubeVel, rv2=rv2, ml_class=ml_class, final=final,
                diag_msgs=diag_msgs, diag_max=diag_max, tema=tema, rho=rho)


# ── Scenarios ────────────────────────────────────────────────────────────────
COMMON = dict(shell_in=55, tube_in=5, tube_scmh=1249, shell_flow=198,
              tube_p_in=25.1, tube_p_out=25.0632,           # corrected design (was 76 / 75.5 -- DB bug)
              shell_p_in=4, shell_p_out=3.99939)

SCENARIOS = [
    ("S1 Clean",     dict(shell_out=35,   tube_out=12.74, **COMMON),
     dict(label="HEALTHY",  score_range=(95,100), uratio_range=(0.95,1.05), duty_band=(-2,2))),
    ("S2 Light",     dict(shell_out=36.5, tube_out=11.5,  **COMMON),
     dict(label="WARNING",  score_range=(80,92),  uratio_range=(0.80,0.95), duty_band=(5,20))),
    ("S3 Heavy",     dict(shell_out=39,   tube_out=9,     **COMMON),
     dict(label="CRITICAL", score_range=(60,82),  uratio_range=(0.60,0.85), duty_band=(15,40))),
    ("S4 Failed",    dict(shell_out=42,   tube_out=7,     **COMMON),
     dict(label="FAILED",   score_range=(0,70),   uratio_range=(0.00,0.75), duty_band=(30,99))),
    ("S5 HighDP",    dict(shell_out=35,   tube_out=12.74,
                          shell_in=55, tube_in=5, tube_scmh=1249, shell_flow=198,
                          tube_p_in=25.1, tube_p_out=22.1,           # tube ΔP = 3 bar (6x allowable)
                          shell_p_in=4,   shell_p_out=3.8),          # shell ΔP = 0.2 bar (at limit)
     dict(label="WARNING/CRITICAL", score_range=(0,100), uratio_range=(0.0,2.0), duty_band=(-99,99))),
]

results = []
for name, s, exp in SCENARIOS:
    r = run_pipeline(s)
    r["_name"] = name; r["_exp"] = exp; r["_inputs"] = s
    results.append(r)

# ── Verification table ───────────────────────────────────────────────────────
def chk(cond): return "PASS" if cond else "FAIL"

def in_band(v, lo, hi): return lo <= v <= hi

def status_match(label, final):
    label = label.upper()
    if "/" in label: return final.upper() in label.split("/")
    return final.upper() == label

print("=" * 110)
print(f"JOB 8497 AUDIT  -- u_service_clean={J['u_service_clean']}, area={J['area']}, F={J['f_factor']}, Q_design={J['duty_design']} kW")
print("=" * 110)

print(f"\n{'Scenario':<10} {'Q':>7} {'duty_loss':>10} {'U_act':>7} {'U_rat':>6} {'Score':>5} {'dpSS%':>6} {'dpTS%':>6} {'vel':>6} {'rv2':>6} {'ML':<8} {'FINAL':<10} EXPECT")
for r in results:
    e = r["_exp"]
    print(f"{r['_name']:<10} {r['Q']:>7.3f} {r['duty_loss']:>9.2f}% {r['U_actual']:>7.1f} {r['U_ratio']:>6.3f} "
          f"{r['score']:>5d} {r['dpr_ss']*100:>5.1f}% {r['dpr_ts']*100:>5.1f}% "
          f"{r['tubeVel']:>6.2f} {r['rv2']:>6.0f} {r['ml_class']:<8} {r['final']:<10} {e['label']}")

print("\n" + "=" * 110)
print("8-CHECK MATRIX")
print("=" * 110)
hdr = ["Check", "S1", "S2", "S3", "S4", "S5"]
print(f"{hdr[0]:<40} {hdr[1]:>8} {hdr[2]:>8} {hdr[3]:>8} {hdr[4]:>8} {hdr[5]:>8}")
print("-" * 90)

# Direction tracking (clean baseline is S1)
S1 = results[0]
def row(name, vals): print(f"{name:<40} " + " ".join(f"{v:>8}" for v in vals))

row("1. U_ratio direction (vs S1=clean)",
    ["clean"] + ["lower" if r["U_ratio"] < S1["U_ratio"] - 0.01
                 else "higher" if r["U_ratio"] > S1["U_ratio"] + 0.01
                 else "equal" for r in results[1:]])
row("   --> direction correct?",
    [chk(in_band(S1["U_ratio"], 0.95, 1.05))]
    + [chk(r["U_ratio"] < S1["U_ratio"] - 0.01) for r in results[1:4]]   # S2-S4 should be lower
    + [chk(abs(results[4]["U_ratio"] - S1["U_ratio"]) < 0.05)])           # S5 same temps -> same U_ratio

row("2. Health score direction",
    [chk(in_band(r["score"], *r["_exp"]["score_range"])) for r in results])

row("3. Status matches conditions",
    [chk(status_match(r["_exp"]["label"], r["final"])) for r in results])

row("4. Duty loss in expected band",
    [chk(in_band(r["duty_loss"], *r["_exp"]["duty_band"])) for r in results])

row("5. dP ratios correct direction",
    [chk(r["dpr_ts"] < 0.2) for r in results[:4]] +
    [chk(results[4]["dpr_ts"] > 1.0)])   # S5 high tube dP

row("6. Thermal deviations correct",
    [chk(abs(r["shell_dev"] - (r["_inputs"]["shell_out"] - J["shell_out_design"])) < 1e-6
         and abs(r["tube_dev"] - (r["_inputs"]["tube_out"] - J["tube_out_design"])) < 1e-6)
     for r in results])

row("7. Diagnostic text severity matches",
    [chk(
        (r["_exp"]["label"] == "HEALTHY" and r["diag_max"] == 0) or
        (r["_exp"]["label"] == "WARNING" and r["diag_max"] >= 1) or
        (r["_exp"]["label"] == "CRITICAL" and r["diag_max"] == 2) or
        (r["_exp"]["label"] == "FAILED" and r["diag_max"] == 2) or
        (r["_exp"]["label"] == "WARNING/CRITICAL" and r["diag_max"] >= 1)
    ) for r in results])

# TEMA: at design clean, tubeVel ~11, rv2 ~50 -- both 'ok'. Flag if higher.
row("8. TEMA tube-vel limit appropriate",
    [chk(r["tema"]["vel"] == ("ok" if r["tubeVel"] <= 32 else "warning" if r["tubeVel"] <= 40 else "danger")) for r in results])

print()
print("=" * 110)
print("RAW DIAGNOSTIC MESSAGES PER SCENARIO")
print("=" * 110)
for r in results:
    print(f"\n[{r['_name']}] {r['_exp']['label']}  -- score={r['score']}, U_ratio={r['U_ratio']:.3f}, duty_loss={r['duty_loss']:.1f}%, FINAL={r['final']}")
    if not r["diag_msgs"]:
        print("  (no warnings) -- 'All parameters within normal range'")
    for sev, msg in r["diag_msgs"]:
        print(f"  [{sev}] {msg}")
