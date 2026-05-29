"""End-to-end validation: hit /calculate_duty via flask test client with the P&L contract."""
import json
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from api import app

client = app.test_client()


def call(label, body, expected_kw=None):
    r = client.post("/calculate_duty", json=body)
    if r.status_code != 200:
        print(f"\n=== {label} ===  HTTP {r.status_code}")
        print(r.get_data(as_text=True))
        return
    j = r.get_json()
    tube = j.get("tube", {})
    print(f"\n=== {label} ===")
    print(f"  backend_used    : {tube.get('backend_used')}")
    print(f"  flow_source     : {tube.get('flow_source')}")
    print(f"  mass_flow_kgh   : {tube.get('flow_kgh')}")
    print(f"  T_in / T_out    : {tube.get('temp_in_c')} C / {tube.get('temp_out_c')} C")
    print(f"  P_in / P_out    : {tube.get('pressure_in_bar_abs')} bara / {tube.get('pressure_out_bar_abs')} bara  ({tube.get('pressure_units')})")
    print(f"  H_in            : {tube.get('h_in_kj_kg')} kJ/kg")
    print(f"  H_out           : {tube.get('h_out_kj_kg')} kJ/kg")
    print(f"  H_delta         : {tube.get('h_delta_kj_kg')} kJ/kg")
    print(f"  Q_kW            : {tube.get('duty_kw')} kW")
    if expected_kw is not None:
        q = tube.get("duty_kw")
        if q is not None:
            err_kw = q - expected_kw
            print(f"  Expected        : {expected_kw} kW   (error: {err_kw:+.4f} kW, {err_kw/expected_kw*100:+.4f} %)")


# Job 8497 — P&L spec inputs
call("Job 8497 (P&L spec, mean_bacton_gas, REFPROP-direct)", {
    "fluid_tube":         "mean_bacton_gas",
    "temp_tube_in":       5.0,
    "temp_tube_out":      12.74,
    "pressure_tube_in":   76.0,     # barg
    "pressure_tube_out":  75.5,     # barg
    "tube_flow_scmh":     1249,
    "std_density":        0.72838,
})

# Job 8541 — main validation
call("Job 8541 (P&L spec, mean_bacton_gas, REFPROP-direct)", {
    "fluid_tube":         "mean_bacton_gas",
    "temp_tube_in":       6.0,
    "temp_tube_out":      4.8633,
    "pressure_tube_in":   85.0,
    "pressure_tube_out":  35.0,
    "tube_flow_scmh":     92585,
    "std_density":        0.72838,
}, expected_kw=1148.87)

# Job 8541 — back-compat: legacy field names + flow_tube_kgh
call("Job 8541 (legacy field names, mean_bacton_gas)", {
    "fluid_tube":              "mean_bacton_gas",
    "temp_in_tube":            6.0,
    "temp_out_tube":           4.8633,
    "pressure_in_tube_bar":    85.0,
    "pressure_out_tube_bar":   35.0,
    "pressure_units":          "barg",
    "flow_tube_kgh":           92585 * 0.72838,
}, expected_kw=1148.87)
