"""Validate REFPROP vs CoolProp HEOS for Mean Bacton Gas — jobs 8497 and 8541."""
import os

RPPREFIX = r"C:\Program Files (x86)\REFPROP"
os.environ["RPPREFIX"] = RPPREFIX

import CoolProp.CoolProp as CP
from ctREFPROP.ctREFPROP import REFPROPFunctionLibrary

RP = REFPROPFunctionLibrary(RPPREFIX)
RP.SETPATHdll(RPPREFIX)

# 14-component .prf composition (Bacton terminal)
RP_FLUIDS = "METHANE;ETHANE;PROPANE;BUTANE;ISOBUTAN;PENTANE;HEXANE;HEPTANE;OCTANE;BENZENE;TOLUENE;NITROGEN;HELIUM;CO2"
RP_Z = [0.9363, 0.0325, 0.0069, 0.0015, 0.0012, 0.0009,
        0.0004, 0.0003, 0.0001, 0.0002, 0.0001, 0.0178, 0.0005, 0.0013]
ierr, herr = RP.SETUPdll(14, RP_FLUIDS, "HMX.BNC", "DEF")
M_RP = RP.WMOLdll(RP_Z)

# 11-component CoolProp HEOS approximation (current api.py)
CP_HEOS = (
    "HEOS::Methane[0.9363]&Ethane[0.0325]&Propane[0.0069]"
    "&n-Butane[0.0015]&IsoButane[0.0012]&n-Pentane[0.0009]"
    "&n-Hexane[0.0004]&n-Heptane[0.0006]&n-Octane[0.0001]"
    "&Nitrogen[0.0183]&CarbonDioxide[0.0013]"
)


def H_refprop_kj_kg(T_C, P_bar_abs):
    r = RP.TPFLSHdll(T_C + 273.15, P_bar_abs * 100.0, RP_Z)
    return r.h / M_RP  # J/mol ÷ g/mol = kJ/kg


def H_coolprop_kj_kg(T_C, P_bar_abs):
    return CP.PropsSI("H", "T", T_C + 273.15, "P", P_bar_abs * 1e5, CP_HEOS) / 1000.0


def run_job(label, scmh, rho_std, T_in_C, P_in_barg, T_out_C, P_out_barg, expected_Q=None):
    m_kgh = scmh * rho_std
    m_kgs = m_kgh / 3600.0

    P_in_abs  = P_in_barg  + 1.01325
    P_out_abs = P_out_barg + 1.01325

    print(f"\n=== {label} ===")
    print(f"  flow_scmh        = {scmh}")
    print(f"  std_density      = {rho_std}")
    print(f"  mass_flow_kgh    = {m_kgh:.4f}")
    print(f"  mass_flow_kgs    = {m_kgs:.6f}")
    print(f"  Inlet :  T = {T_in_C} C,  P = {P_in_barg} barg ({P_in_abs:.5f} bara)")
    print(f"  Outlet:  T = {T_out_C} C,  P = {P_out_barg} barg ({P_out_abs:.5f} bara)")

    for name, H in (("REFPROP (14-comp .prf)", H_refprop_kj_kg),
                    ("CoolProp HEOS (11-comp)", H_coolprop_kj_kg)):
        Hi = H(T_in_C,  P_in_abs)
        Ho = H(T_out_C, P_out_abs)
        dH = Ho - Hi
        Q  = dH * m_kgh / 3600.0
        diff = "" if expected_Q is None else f"   |Q-Q_expected| = {abs(Q-expected_Q):.4f} kW"
        print(f"\n  [{name}]")
        print(f"    H_in   = {Hi:.5f} kJ/kg")
        print(f"    H_out  = {Ho:.5f} kJ/kg")
        print(f"    dH     = {dH:.5f} kJ/kg")
        print(f"    Q      = {Q:.5f} kW{diff}")


run_job("Job 8497", scmh=1249,  rho_std=0.72838,
        T_in_C=5.0,  P_in_barg=76.0,
        T_out_C=12.74, P_out_barg=75.5)

run_job("Job 8541", scmh=92585, rho_std=0.72838,
        T_in_C=6.0, P_in_barg=85.0,
        T_out_C=4.8633, P_out_barg=35.0,
        expected_Q=1148.87)
