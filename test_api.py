"""
Quick smoke-test for the Predictive Maintenance API.
Run while api.py is running:   python test_api.py
"""
import json
import urllib.request
import urllib.error

BASE = "http://localhost:5000"

# ── Sample payload (taken from exchanger 8257, first row) ─────────────────────
SAMPLE = {
    # Heat transfer
    "HeatTranRatClean": 469.0927,
    "HeatTranRatDirty": 469.0927,
    # Pressure drop (calculated)
    "PresDropCalcSS": 0.01899143,
    "PresDropCalcTS": 0.02681944,
    # Pressure drop (allowed) — for derived ratio features
    "PresDropAlloSS": 0.2,
    "PresDropAlloTS": 0.2,
    # EDR DP ratios
    "DPratioSS": 0.09495714,
    "DPratioTS": 0.1340972,
    # Fouling
    "FoulResSS": 0.0,
    "FoulResTS": 0.0,
    # Thermal
    "LMTD": 34.10085,
    "MTDCorrFactor": 1.00082,
    # Velocities
    "VelThruTubesMaxTS": 8.035466,
    "VelCrossFlowMaxSS": 0.1567225,
    "RV2BundleEnt": 60.1122,
    "RV2InNoz": 1291.233,
    # Geometry
    "TubeNum": 105,
    "TubeOD": 19.05,
    "TubeID": 15.75,
    "TubeLng": 1804,
    "ShlID": 304.86,
    "BafNum": 9,
    "BafSpcCC": 160,
    "BafCutPerc": 22.94205,
    "TubePassNum": 1,
    "Area": 10.3057,
    # Operating conditions
    "TempInSS": 55,
    "TempInTS": 5,
    "FlRaTotalSS": 5999.15137,
    "FlRaTotalTS": 15509.999,
    "PresOperInSS": 4,
    "PresOperInTS": 34.1,
    "FilmCoefSS": 1270.626,
    "FilmCoefTS": 763.4376,
}


def _call(method, path, body=None):
    url  = BASE + path
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def run():
    print("=" * 55)
    print("Predictive Maintenance API — smoke test")
    print("=" * 55)

    # Health
    print("\n[GET /health]")
    h = _call("GET", "/health")
    print(json.dumps(h, indent=2))

    # Features
    print("\n[GET /features]")
    f = _call("GET", "/features")
    print(f"  raw_inputs ({len(f['raw_inputs'])}): {f['raw_inputs'][:5]} ...")
    print(f"  derived   : {list(f['derived_features'].keys())}")

    # Predict (clean baseline)
    print("\n[POST /predict]  — clean exchanger (zero fouling)")
    r = _call("POST", "/predict", SAMPLE)
    print(json.dumps(r, indent=2))

    # Predict (heavy fouling)
    fouled = dict(SAMPLE)
    fouled["HeatTranRatDirty"] = 320.0   # significant U drop
    fouled["FoulResSS"]  = 0.00095
    fouled["FoulResTS"]  = 0.00095
    print("\n[POST /predict]  — fouled exchanger (heavy fouling)")
    r2 = _call("POST", "/predict", fouled)
    print(json.dumps(r2, indent=2))

    print("\nAll tests passed.")


if __name__ == "__main__":
    try:
        run()
    except urllib.error.URLError as e:
        print(f"\nERROR - Cannot reach API: {e}")
        print("  Make sure api.py is running: start_api.bat")
