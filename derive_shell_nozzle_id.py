"""
Derive shell_nozzle_id_mm for every job and write it into job_database.json.

Path B (live shell-side RhoV²) needs a shell nozzle inside diameter, which is
NOT present in any source CSV. We back-solve it from the EDR-reported design
nozzle RhoV² (rv2_nozzle_design, already in the DB) at design conditions:

    RhoV²  = mdot² / (rho · A²)          (rho·V² with V = mdot/(rho·A))
  =>  A    = mdot / sqrt(rho · RhoV²)
  =>  ID   = sqrt(4A/π)

  mdot = shell_flow_design_kgh / 3600                 (design shell mass flow)
  rho  = glycol density at mean shell T & shell P     (/fluid_props, 40% MEG)

Validation (run separately): the implied IDs land within ~2 mm of standard pipe
schedule IDs for 39/42 jobs, confirming the formula + density basis match EDR.

The EXACT back-solved ID is stored (not rounded to a standard size) so the live
dashboard calc reproduces rv2_nozzle_design exactly at design shell flow.

Jobs with ~zero design shell flow (8364-A, 8471) cannot be back-solved; they get
shell_nozzle_id_mm = null and the dashboard falls back to the static EDR value.
"""
import json, math, urllib.request

DB = "job_database.json"
API = "http://127.0.0.1:5000/fluid_props"
MIN_FLOW_KGS = 0.01   # below this, design flow is ~0 -> cannot back-solve


def glycol_density(T_c, P_barg, glycol_pct):
    body = json.dumps({
        "fluid": "glycol", "temp_c": T_c, "pressure_bar": P_barg,
        "pressure_units": "barg", "glycol_pct": glycol_pct,
        "glycol_type": "ethylene",
    }).encode()
    req = urllib.request.Request(API, data=body,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=20))["density_kg_m3"]


def main():
    jobs = json.loads(open(DB, encoding="utf-8-sig").read())
    derived, skipped = 0, []
    for j in jobs:
        jid = str(j.get("job_id"))
        rv2 = float(j.get("rv2_nozzle_design") or 0)
        mdot = float(j.get("shell_flow_design_kgh") or 0) / 3600.0
        if rv2 <= 0 or mdot < MIN_FLOW_KGS:
            j["shell_nozzle_id_mm"] = None
            skipped.append(jid)
            continue
        T = (float(j["shell_in_design"]) + float(j["shell_out_design"])) / 2.0
        P_in = float(j.get("shell_press_design_barg", 4.0))
        P_out = float(j.get("shell_press_out_design_barg", P_in))
        P = (P_in + P_out) / 2.0
        rho = glycol_density(T, P, float(j.get("glycol_pct", 40)))
        A = mdot / math.sqrt(rho * rv2)
        D_mm = math.sqrt(4 * A / math.pi) * 1000.0
        j["shell_nozzle_id_mm"] = round(D_mm, 4)
        derived += 1
        print(f"{jid:8} rho={rho:7.1f}  mdot={mdot:8.3f}  rv2={rv2:9.1f}  ->  ID={D_mm:7.2f} mm")

    with open(DB, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=4, ensure_ascii=False)
        f.write("\n")
    print(f"\nDerived {derived} nozzle IDs; {len(skipped)} skipped (null): {skipped}")


if __name__ == "__main__":
    main()
