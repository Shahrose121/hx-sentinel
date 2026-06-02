"""
HX Sentinel — PART 1 AUDIT ONLY.
Replicates dashboard.html runAnalysis() math exactly, calling the live API
for enthalpy (/fluid_props) and ML class (/predict). No edits to dashboard.
"""
import json, math, urllib.request

API = "http://127.0.0.1:5000"

def post(path, body):
    req = urllib.request.Request(API+path, data=json.dumps(body).encode(),
                                 headers={"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(req, timeout=20))

# ── Design basis (job 8497) ──────────────────────────────────────────────
J = {j["job_id"]: j for j in json.load(open("job_database.json", encoding="utf-8-sig"))}["8497"]
shellOutD = J["tube_out_design"]*0 + J["shell_out_design"]
tubeOutD  = J["tube_out_design"]
stdDens   = J["std_density"]
dutyDesign= J["duty_design"]
uServiceClean = J["u_service_clean"]
area      = J["area"]
fFactor   = J["f_factor"]
dpAlloSS  = J["dp_allow_ss"]
dpAlloTS  = J["dp_allow_ts"]

SEV = {"healthy":0,"warning":1,"critical":2,"failed":3}
worseOf = lambda a,b: a if SEV[a]>=SEV[b] else b

def gas_h(t,p):
    return post("/fluid_props",{"fluid":"mean_bacton_gas","temp_c":t,
        "pressure_bar":p,"pressure_units":"barg","prefer_refprop":True})

def run(name, sr):
    # site readings
    shellInA=sr["shell_in"]; shellOutA=sr["shell_out"]
    tubeInA=sr["tube_in"];   tubeOutA=sr["tube_out"]
    tubeFlowSCMH=sr["tube_flow"]
    shellPresInA=sr["shell_pres_in"]; shellPresOutA=sr["shell_pres_out"]
    tubePresInA=sr["tube_pres_in"];   tubePresOutA=sr["tube_pres_out"]

    # PART 3 FIX 4: validate pressures before computing
    if tubePresOutA>=tubePresInA or shellPresOutA>=shellPresInA:
        return dict(name=name,blocked="Outlet pressure must be below inlet pressure")

    dpSS=max(0,shellPresInA-shellPresOutA)
    dpTS=max(0,tubePresInA-tubePresOutA)

    fpIn=gas_h(tubeInA,tubePresInA); h_in=fpIn["h_kj_kg"]
    fpOut=gas_h(tubeOutA,tubePresOutA); h_out=fpOut["h_kj_kg"]

    tubeMassFlow_kgh=tubeFlowSCMH*stdDens
    Q_kW=(h_out-h_in)*tubeMassFlow_kgh/3600

    dT1=shellInA-tubeOutA; dT2=shellOutA-tubeInA
    if abs(dT1-dT2)<0.001: LMTD=dT1
    elif dT1<=0 or dT2<=0 or dT1/dT2<=0: LMTD=(dT1+dT2)/2
    else: LMTD=(dT1-dT2)/math.log(dT1/dT2)
    U_actual=(Q_kW*1000)/(area*LMTD*fFactor) if (LMTD>0 and area>0 and fFactor>0) else 0

    U_ratio=U_actual/uServiceClean
    duty_loss_pct=(dutyDesign-Q_kW)/dutyDesign*100 if dutyDesign>0 else 0
    tube_dev=tubeOutA-tubeOutD
    dp_ratio_SS=dpSS/dpAlloSS if dpAlloSS>0 else 0
    dp_ratio_TS=dpTS/dpAlloTS if dpAlloTS>0 else 0

    geo=J
    mlPayload={"HeatTranRatClean":uServiceClean,"HeatTranRatDirty":U_actual,
      "U_ratio":U_ratio,"PresDropCalcSS":dpSS,"PresDropCalcTS":dpTS,
      "PresDropAlloSS":dpAlloSS,"PresDropAlloTS":dpAlloTS,"DPratioSS":dp_ratio_SS,
      "DPratioTS":dp_ratio_TS,"VelThruTubesMaxTS":geo["vel_ts_design"],
      "RV2InNoz":geo["rv2_nozzle_design"],"FoulResSS":0.000352,"FoulResTS":0.000176,
      "LMTD":LMTD,"MTDCorrFactor":fFactor,"TempInSS":shellInA,"TempInTS":tubeInA,
      "FilmCoefSS":geo["film_coef_ss"],"FilmCoefTS":geo["film_coef_ts"],
      "TubeNum":geo["tube_num"],"TubeOD":geo["tube_od"],"TubeID":geo["tube_id"],
      "TubeLng":geo["tube_lng"],"ShlID":geo["shl_id"],"BafNum":geo["baf_num"],
      "BafSpcCC":geo["baf_spc"],"BafCutPerc":geo["baf_cut"],"TubePassNum":geo["tube_pass"],
      "Area":area,"FlRaTotalSS":sr["shell_flow"],"FlRaTotalTS":tubeMassFlow_kgh,
      "PresOperInSS":shellPresInA,"PresOperInTS":tubePresInA,
      "DP_shell_ratio":dp_ratio_SS,"DP_tube_ratio":dp_ratio_TS,
      "VelCrossFlowMaxSS":geo["vel_cross_design"],"RV2BundleEnt":geo["rv2_bundle_design"]}
    ml=post("/predict",mlPayload)
    finalClass=ml["maintenance_class"]

    # overrides (exact copy of dashboard logic)
    if   duty_loss_pct>40: finalClass="failed"
    elif duty_loss_pct>20: finalClass="critical"
    elif duty_loss_pct>5:  finalClass="warning"
    if   tube_dev<-3: finalClass=worseOf(finalClass,"critical")
    elif tube_dev<-1: finalClass=worseOf(finalClass,"warning")
    maxDp=max(dp_ratio_SS,dp_ratio_TS)
    if   maxDp>1.0: finalClass=worseOf(finalClass,"critical")
    elif maxDp>0.8: finalClass=worseOf(finalClass,"warning")

    # PART 3 FIX 2: cap health-side U_ratio at 1.0 + duty-exceeds clamp
    urHealth=min(U_ratio,1.0)
    note=""
    if Q_kW>dutyDesign*1.15:
        urHealth=1.0; note="duty>design*1.15"
    # PART 3 FIX 1: score band derived from finalClass
    band={"healthy":(85,100),"warning":(60,84),"critical":(35,59),"failed":(0,34)}[finalClass]
    lo,hi=band
    frac=max(0,min(1,urHealth))
    ring_score=round(max(lo,min(hi,lo+(hi-lo)*frac)))
    band_ok = lo<=ring_score<=hi
    return dict(name=name,Q_kW=Q_kW,U_actual=U_actual,U_ratio=U_ratio,
        ring_score=ring_score,status=finalClass,ml_raw=ml["maintenance_class"],
        dp_ratio_TS=dp_ratio_TS,duty_loss_pct=duty_loss_pct,band_ok=band_ok,
        note=note,tubePresInA=tubePresInA,tubePresOutA=tubePresOutA)

base=dict(shell_in=55,shell_flow=197.6092,tube_in=5,tube_flow=1249.9999,
          shell_pres_in=4.0,shell_pres_out=3.999388,
          tube_pres_in=25.1,tube_pres_out=25.0632)
def C(**kw): d=dict(base); d.update(kw); return d

cases=[
 ("1 Clean",          C(shell_out=35.0, tube_out=12.74)),
 ("2 Light foul",     C(shell_out=36.5, tube_out=11.5)),
 ("3 Heavy foul",     C(shell_out=39.0, tube_out=9.0)),
 ("4 High tube dP",   C(shell_out=35.0, tube_out=12.74, tube_pres_in=25.1, tube_pres_out=20.0)),
 ("5 Outlet>Inlet P", C(shell_out=35.0, tube_out=12.74, tube_pres_in=25.0, tube_pres_out=30.0)),
]

rows=[run(n,sr) for n,sr in cases]

hdr=f"{'Case':<16}{'Q_kW':>8}{'U_act':>8}{'U_ratio':>9}{'ring':>6}{'status':>10}{'ML':>9}{'dpTS_r':>8}{'dutyL%':>8}{'band':>8}{'note':>20}"
print(hdr); print("-"*len(hdr))
for r in rows:
    if r.get("blocked"):
        print(f"{r['name']:<16}{'BLOCKED — '+r['blocked']:>}")
        continue
    flag="OK" if r["band_ok"] else "MISMATCH"
    print(f"{r['name']:<16}{r['Q_kW']:>8.3f}{r['U_actual']:>8.1f}{r['U_ratio']:>9.3f}"
          f"{r['ring_score']:>6}{r['status']:>10}{r['ml_raw']:>9}{r['dp_ratio_TS']:>8.2f}"
          f"{r['duty_loss_pct']:>8.1f}{flag:>8}{r['note']:>20}")
