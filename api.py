"""
Predictive Maintenance API — EDR_ML
Flask app that loads trained GBM models and returns
maintenance class + area ratio from site readings.

Endpoints
---------
GET  /health            Liveness check
GET  /features          List model input fields
POST /predict           ML maintenance class + area ratio
POST /calculate_duty    CoolProp fluid properties + heat duty
POST /fluid_props       Single-point CoolProp lookup (mean_bacton_gas, glycol, etc.)
"""

import os
import pickle
import warnings
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
import CoolProp.CoolProp as CP

warnings.filterwarnings("ignore")

try:
    _rp_version = CP.get_global_param_string("REFPROP_version")
    REFPROP_VERSION = _rp_version if _rp_version and _rp_version.lower() != "n/a" else None
except Exception:
    REFPROP_VERSION = None
REFPROP_AVAILABLE = REFPROP_VERSION is not None

# ── Direct ctREFPROP (used for mean_bacton_gas — 14-component .prf fidelity) ───
RPPREFIX = os.environ.get("RPPREFIX", r"C:\Program Files (x86)\REFPROP")
BACTON_RP_FLUIDS = ("METHANE;ETHANE;PROPANE;BUTANE;ISOBUTAN;PENTANE;HEXANE;"
                    "HEPTANE;OCTANE;BENZENE;TOLUENE;NITROGEN;HELIUM;CO2")
BACTON_RP_Z = [0.9363, 0.0325, 0.0069, 0.0015, 0.0012, 0.0009,
               0.0004, 0.0003, 0.0001, 0.0002, 0.0001, 0.0178, 0.0005, 0.0013]

try:
    from ctREFPROP.ctREFPROP import REFPROPFunctionLibrary as _RPLib
    _RP = _RPLib(RPPREFIX)
    _RP.SETPATHdll(RPPREFIX)
    _ierr, _herr = _RP.SETUPdll(14, BACTON_RP_FLUIDS, "HMX.BNC", "DEF")
    BACTON_RP_M = _RP.WMOLdll(BACTON_RP_Z)  # g/mol
    REFPROP_DIRECT_AVAILABLE = True
    print(f"REFPROP direct ready: Bacton mixture M = {BACTON_RP_M:.4f} g/mol", flush=True)
except Exception as _e:
    _RP = None
    BACTON_RP_M = None
    REFPROP_DIRECT_AVAILABLE = False
    print(f"REFPROP direct unavailable: {_e}", flush=True)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

# ── Load models at startup ─────────────────────────────────────────────────────
def _load(name):
    path = os.path.join(MODELS_DIR, name)
    with open(path, "rb") as f:
        return pickle.load(f)

print("Loading models …", flush=True)
CLASSIFIER    = _load("classifier.pkl")      # GradientBoostingClassifier
REGRESSOR     = _load("regressor.pkl")       # GradientBoostingRegressor
LABEL_ENCODER = _load("label_encoder.pkl")   # LabelEncoder → [critical, failed, healthy, warning]
FEATURE_COLS  = _load("feature_cols.pkl")    # list of 35 feature names
print(f"  classifier   : {type(CLASSIFIER).__name__}")
print(f"  regressor    : {type(REGRESSOR).__name__}")
print(f"  label classes: {list(LABEL_ENCODER.classes_)}")
print(f"  features     : {len(FEATURE_COLS)} columns")
print("Models ready.\n", flush=True)

# ── Feature engineering ────────────────────────────────────────────────────────
# Three columns are derived before model input:
#   U_ratio        = HeatTranRatDirty / HeatTranRatClean   (fouling's effect on U)
#   DP_shell_ratio = PresDropCalcSS   / PresDropAlloSS     (shell-side DP utilisation)
#   DP_tube_ratio  = PresDropCalcTS   / PresDropAlloTS     (tube-side  DP utilisation)
#
# The remaining 32 columns come directly from the EDR simulation / site instrument
# readings. PresDropAlloSS and PresDropAlloTS are needed only for the derivation
# and are NOT fed to the model directly.

RAW_INPUTS = [
    # Thermal / heat transfer
    "HeatTranRatClean", "HeatTranRatDirty",
    # Pressure drop (calculated)
    "PresDropCalcSS", "PresDropCalcTS",
    # Pressure drop (allowed) — used only to compute derived ratios
    "PresDropAlloSS", "PresDropAlloTS",
    # Existing ratio columns (from EDR)
    "DPratioSS", "DPratioTS",
    # Fouling
    "FoulResSS", "FoulResTS",
    # Thermal correction
    "LMTD", "MTDCorrFactor",
    # Velocities / vibration
    "VelThruTubesMaxTS", "VelCrossFlowMaxSS",
    "RV2BundleEnt", "RV2InNoz",
    # Geometry
    "TubeNum", "TubeOD", "TubeID", "TubeLng",
    "ShlID", "BafNum", "BafSpcCC", "BafCutPerc",
    "TubePassNum", "Area",
    # Operating conditions
    "TempInSS", "TempInTS",
    "FlRaTotalSS", "FlRaTotalTS",
    "PresOperInSS", "PresOperInTS",
    "FilmCoefSS", "FilmCoefTS",
]


def _build_feature_vector(data: dict) -> np.ndarray:
    """Validate inputs, compute derived features, and return ordered feature array."""

    missing = [k for k in RAW_INPUTS if k not in data]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    def _f(key):
        v = data[key]
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Field '{key}' must be numeric, got: {v!r}")

    # Raw values
    u_clean      = _f("HeatTranRatClean")
    u_dirty      = _f("HeatTranRatDirty")
    dp_calc_ss   = _f("PresDropCalcSS")
    dp_calc_ts   = _f("PresDropCalcTS")
    dp_allo_ss   = _f("PresDropAlloSS")
    dp_allo_ts   = _f("PresDropAlloTS")

    # Guard against division by zero
    if u_clean == 0:
        raise ValueError("HeatTranRatClean cannot be zero (used as denominator for U_ratio)")
    if dp_allo_ss == 0:
        raise ValueError("PresDropAlloSS cannot be zero (used as denominator for DP_shell_ratio)")
    if dp_allo_ts == 0:
        raise ValueError("PresDropAlloTS cannot be zero (used as denominator for DP_tube_ratio)")

    # Derived features
    u_ratio        = u_dirty      / u_clean
    dp_shell_ratio = dp_calc_ss   / dp_allo_ss
    dp_tube_ratio  = dp_calc_ts   / dp_allo_ts

    # Build feature lookup (derived + raw)
    derived = {
        "U_ratio":        u_ratio,
        "DP_shell_ratio": dp_shell_ratio,
        "DP_tube_ratio":  dp_tube_ratio,
    }
    all_vals = {**derived, **{k: _f(k) for k in RAW_INPUTS if k not in ("PresDropAlloSS", "PresDropAlloTS")}}

    # Assemble in the exact order the models expect
    try:
        vector = np.array([all_vals[col] for col in FEATURE_COLS], dtype=float)
    except KeyError as e:
        raise ValueError(f"Feature column {e} could not be resolved from inputs")

    return vector, derived


# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    """Quick liveness check."""
    return jsonify({
        "status":        "ok",
        "models_loaded": True,
        "label_classes": list(LABEL_ENCODER.classes_),
        "n_features":    len(FEATURE_COLS),
        "refprop_available": REFPROP_AVAILABLE,
        "refprop_version": REFPROP_VERSION,
    })


@app.route("/features", methods=["GET"])
def features():
    """Return expected input fields and derived feature formulas."""
    return jsonify({
        "raw_inputs":    RAW_INPUTS,
        "derived_features": {
            "U_ratio":        "HeatTranRatDirty / HeatTranRatClean",
            "DP_shell_ratio": "PresDropCalcSS   / PresDropAlloSS",
            "DP_tube_ratio":  "PresDropCalcTS   / PresDropAlloTS",
        },
        "model_feature_order": FEATURE_COLS,
        "note": (
            "PresDropAlloSS and PresDropAlloTS are used only to compute the derived "
            "ratio features — they are not passed directly to the models."
        ),
    })


@app.route("/predict", methods=["POST"])
def predict():
    """
    Accept site readings as JSON, return maintenance class + area ratio.

    Request body (JSON):
        All keys listed in GET /features → raw_inputs

    Response:
        {
          "maintenance_class": "warning",
          "maintenance_class_probabilities": { "critical": 0.05, ... },
          "area_ratio": 1.07,
          "area_ratio_label": "warning",
          "derived_features": { "U_ratio": 0.92, ... }
        }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    # ── Build feature vector ───────────────────────────────────────────────────
    try:
        X, derived = _build_feature_vector(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    X2d = X.reshape(1, -1)

    # ── Classifier ────────────────────────────────────────────────────────────
    class_idx    = CLASSIFIER.predict(X2d)[0]
    class_label  = LABEL_ENCODER.inverse_transform([class_idx])[0]
    class_proba  = CLASSIFIER.predict_proba(X2d)[0]
    proba_dict   = {
        cls: round(float(p), 4)
        for cls, p in zip(LABEL_ENCODER.classes_, class_proba)
    }

    # ── Regressor ─────────────────────────────────────────────────────────────
    area_ratio = float(REGRESSOR.predict(X2d)[0])

    # ── Area ratio label ──────────────────────────────────────────────────────
    if area_ratio > 1.10:
        ar_label = "healthy"
    elif area_ratio >= 1.02:
        ar_label = "warning"
    elif area_ratio >= 1.00:
        ar_label = "critical"
    else:
        ar_label = "failed"

    return jsonify({
        "maintenance_class":                class_label,
        "maintenance_class_probabilities":  proba_dict,
        "area_ratio":                       round(area_ratio, 6),
        "area_ratio_label":                 ar_label,
        "derived_features": {
            k: round(v, 6) for k, v in derived.items()
        },
    })


# ── CoolProp fluid helpers ─────────────────────────────────────────────────────

# Common fluid aliases → CoolProp backend names
_FLUID_ALIASES = {
    "water":         "Water",
    "natural-gas":   "Methane",      # methane is a good approx for lean nat. gas
    "methane":       "Methane",
    "ethane":        "Ethane",
    "propane":       "Propane",
    "butane":        "n-Butane",
    "nitrogen":      "Nitrogen",
    "co2":           "CarbonDioxide",
    "carbon-dioxide":"CarbonDioxide",
    "steam":         "Water",
    "air":           "Air",
}

# glycol_type keyword → CoolProp INCOMP prefix
_GLYCOL_MAP = {
    "ethylene":  "MEG",   # mono-ethylene glycol
    "propylene": "MPG",   # mono-propylene glycol
    "meg":       "MEG",
    "mpg":       "MPG",
    "eg":        "MEG",
    "pg":        "MPG",
}


def _resolve_fluid(name: str, glycol_pct=None, glycol_type="ethylene"):
    """
    Return (coolprop_fluid_string, human_display_name).

    water-glycol  → "INCOMP::MEG[0.40]"   (mass fraction, ethylene glycol default)
    natural-gas   → "Methane"              (methane approximation, noted in response)
    water         → "Water"
    <anything>    → passed straight to CoolProp (allows direct backend names)
    """
    key = name.lower().strip()

    # ── Water-glycol mixture ──────────────────────────────────────────────────
    if key == "water-glycol":
        if glycol_pct is None:
            raise ValueError("glycol_pct (mass %) is required for water-glycol")
        frac = float(glycol_pct) / 100.0
        if not (0.01 <= frac <= 0.99):
            raise ValueError(f"glycol_pct must be 1–99, got {glycol_pct}")
        gprefix = _GLYCOL_MAP.get(str(glycol_type).lower(), "MEG")
        cp_str  = f"INCOMP::{gprefix}[{frac:.4f}]"
        gname   = "ethylene" if gprefix == "MEG" else "propylene"
        display = f"{glycol_pct}% {gname}-glycol / water (mass fraction)"
        return cp_str, display

    # ── Named alias ──────────────────────────────────────────────────────────
    if key in _FLUID_ALIASES:
        cp_str = _FLUID_ALIASES[key]
        note   = " — methane approx." if key == "natural-gas" else ""
        return cp_str, name + note

    # ── Direct CoolProp name (e.g. "R134a", "INCOMP::DowQ[0.3]") ─────────────
    return name, name


def _props_at(cp_fluid: str, T_C: float, P_bar: float) -> dict:
    """
    Query CoolProp for Cp, density, viscosity, conductivity (and Z for gases).
    Returns a flat dict with rounded values ready for JSON.
    """
    T_K  = T_C + 273.15
    P_Pa = P_bar * 1e5
    out  = {}

    try:
        out["cp_kj_kgk"]          = round(CP.PropsSI("C", "T", T_K, "P", P_Pa, cp_fluid) / 1000, 5)
        out["density_kg_m3"]      = round(CP.PropsSI("D", "T", T_K, "P", P_Pa, cp_fluid), 4)
        out["viscosity_mPas"]     = round(CP.PropsSI("V", "T", T_K, "P", P_Pa, cp_fluid) * 1000, 6)
        out["conductivity_W_mK"]  = round(CP.PropsSI("L", "T", T_K, "P", P_Pa, cp_fluid), 6)
    except Exception as e:
        raise ValueError(f"CoolProp failed for '{cp_fluid}' at T={T_C}°C, P={P_bar} bar: {e}")

    # Compressibility factor — meaningful for real gases, silently skipped for liquids
    try:
        out["Z_compressibility"] = round(CP.PropsSI("Z", "T", T_K, "P", P_Pa, cp_fluid), 5)
    except Exception:
        out["Z_compressibility"] = None

    return out


def _pick(data: dict, *keys, default=None, required: bool = False):
    """Return the first present value among `keys`; raise if required and none found."""
    for k in keys:
        if k in data:
            return data[k]
    if required:
        raise ValueError(f"Missing required field — provide one of: {list(keys)}")
    return default


def _mass_flow_kgh(data: dict, prefix: str):
    """
    Resolve mass flow (kg/h) for a side.
    Preferred:  {prefix}_flow_scmh × std_density   (P&L standard)
    Fallback:   flow_{prefix}_kgh
    Returns (mass_flow_kgh, source_dict) or (None, None) when no flow given.
    """
    scmh_key = f"{prefix}_flow_scmh"
    if scmh_key in data:
        scmh = float(data[scmh_key])
        rho_std = float(_pick(data, f"std_density_{prefix}", "std_density", required=True))
        return scmh * rho_std, {
            "method":       "scmh_x_std_density",
            "flow_scmh":    scmh,
            "std_density":  rho_std,
        }
    kgh_key = f"flow_{prefix}_kgh"
    if kgh_key in data:
        return float(data[kgh_key]), {"method": "direct_kgh"}
    return None, None


def _calc_side(data: dict, prefix: str) -> dict:
    """
    Build one side (shell or tube) of the duty calculation.
    prefix is 'shell' or 'tube'.

    Inputs (preferred new names → legacy fallbacks):
        fluid_{prefix}
        temp_{prefix}_in   ← temp_in_{prefix}      (°C)
        temp_{prefix}_out  ← temp_out_{prefix}     (°C)
        pressure_{prefix}_in   (barg, default)  ← pressure_in_{prefix}_bar (units per pressure_units)
        pressure_{prefix}_out  (barg, default)  ← pressure_out_{prefix}_bar
        {prefix}_flow_scmh + std_density   ← flow_{prefix}_kgh

    duty_kw is None when no flow rate is supplied.
    """
    fluid_key = f"fluid_{prefix}"
    if fluid_key not in data:
        return None

    glycol_pct  = data.get("glycol_pct")
    glycol_type = data.get("glycol_type", "ethylene")

    T_in  = float(_pick(data, f"temp_{prefix}_in",  f"temp_in_{prefix}",  required=True))
    T_out = float(_pick(data, f"temp_{prefix}_out", f"temp_out_{prefix}", required=True))

    # Pressure: new names (pressure_{prefix}_in / _out) are barg per P&L spec.
    # Legacy names (pressure_in_{prefix}_bar etc.) use pressure_units (default bar_abs).
    new_p_in_key  = f"pressure_{prefix}_in"
    new_p_out_key = f"pressure_{prefix}_out"
    if new_p_in_key in data or new_p_out_key in data:
        pressure_units = data.get(f"pressure_units_{prefix}", data.get("pressure_units", "barg"))
        P_in_input  = float(_pick(data, new_p_in_key,  required=True))
        P_out_input = float(_pick(data, new_p_out_key, required=True))
    else:
        pressure_units = data.get(f"pressure_units_{prefix}", data.get("pressure_units", "bar_abs"))
        P_default = float(data.get(f"pressure_{prefix}_bar", 1.01325))
        P_in_input  = float(data.get(f"pressure_in_{prefix}_bar",  data.get(f"pressure_{prefix}_in_bar",  P_default)))
        P_out_input = float(data.get(f"pressure_out_{prefix}_bar", data.get(f"pressure_{prefix}_out_bar", P_default)))

    P_in_bar,  _ = _pressure_abs_bar(P_in_input,  pressure_units)
    P_out_bar, _ = _pressure_abs_bar(P_out_input, pressure_units)
    T_mean = (T_in + T_out) / 2.0
    P_mean_bar = (P_in_bar + P_out_bar) / 2.0  # absolute bar
    dT = abs(T_in - T_out)

    # Mean properties for reporting (always pass bar_abs since we already converted).
    props = _fluid_props_backend(
        fluid_name     = str(data[fluid_key]),
        temp_c         = T_mean,
        pressure_bar   = P_mean_bar,
        glycol_pct     = glycol_pct,
        glycol_type    = glycol_type,
        pressure_units = "bar_abs",
    )

    side = {
        "fluid":              props["fluid"],
        "coolprop_fluid":     props["coolprop_fluid"],
        "refprop_fluid":      props.get("refprop_fluid"),
        "backend_used":       props["backend_used"],
        "enthalpy_units":     props["enthalpy_units"],
        "temp_in_c":          T_in,
        "temp_out_c":         T_out,
        "temp_mean_c":        round(T_mean, 4),
        "delta_T_c":          round(dT, 4),
        "pressure_in_bar_abs":  round(P_in_bar, 6),
        "pressure_out_bar_abs": round(P_out_bar, 6),
        "pressure_in_input":   P_in_input,
        "pressure_out_input":  P_out_input,
        "pressure_units":      pressure_units,
        "pressure_bar":        props["pressure_bar"],
        "pressure_abs_bar":    props["pressure_abs_bar"],
        "cp_kj_kgk":           props["cp_kj_kgk"],
        "density_kg_m3":       props["density_kg_m3"],
        "viscosity_mPas":      props["viscosity_mPas"],
        "conductivity_W_mK":   props["conductivity_W_mK"],
        "Z_compressibility":   props["Z_compressibility"],
        "duty_kw":             None,
    }

    mass_kgh, flow_info = _mass_flow_kgh(data, prefix)
    if mass_kgh is not None:
        p_in  = _fluid_props_backend(str(data[fluid_key]), T_in,  P_in_bar,  glycol_pct,
                                     glycol_type, "bar_abs")
        p_out = _fluid_props_backend(str(data[fluid_key]), T_out, P_out_bar, glycol_pct,
                                     glycol_type, "bar_abs")
        if p_in.get("h_kj_kg") is None or p_out.get("h_kj_kg") is None:
            raise ValueError("enthalpy unavailable; cannot compute duty by enthalpy method")
        h_delta = p_out["h_kj_kg"] - p_in["h_kj_kg"]
        duty = h_delta * mass_kgh / 3600.0
        side["flow_kgh"]      = round(mass_kgh, 5)
        side["flow_kg_s"]     = round(mass_kgh / 3600.0, 6)
        side["flow_source"]   = flow_info
        side["h_in_kj_kg"]    = round(p_in["h_kj_kg"], 5)
        side["h_out_kj_kg"]   = round(p_out["h_kj_kg"], 5)
        side["h_delta_kj_kg"] = round(h_delta, 5)
        side["duty_kw"]       = round(duty, 5)

    return side


# ── /calculate_duty ────────────────────────────────────────────────────────────

@app.route("/calculate_duty", methods=["POST"])
def calculate_duty():
    """
    POST /calculate_duty

    Calculate exact fluid properties and heat duty using CoolProp 7.

    Supported fluids
    ----------------
    fluid_shell / fluid_tube:
        "water-glycol"    requires glycol_pct (mass%), optional glycol_type
                          ("ethylene" default | "propylene")
        "natural-gas"     methane approximation (accurate for lean gas)
        "water"           pure water
        "methane", "ethane", "propane", "nitrogen", "co2", "air"
        Any CoolProp backend name (e.g. "R134a", "INCOMP::DowQ[0.3]")

    Duty formula (P&L engineering standard, Job 8541)
    --------------------------------------------------
        mass_flow_kgh = flow_scmh × std_density
        H_in  = enthalpy at (T_in,  P_in)
        H_out = enthalpy at (T_out, P_out)
        Q_kW  = (H_out − H_in) × mass_flow_kgh / 3600

    "mean_bacton_gas" is routed through ctREFPROP with the 14-component
    Bacton terminal composition (Toluene, Benzene, Helium included) and does
    NOT fall back to CoolProp HEOS. Other fluids use REFPROP-first with HEOS
    fallback.

    Inputs (per side — temperatures °C, pressures barg by default)
    ---------------------------------------------------------------
    Preferred (P&L dashboard contract):
        fluid_{shell|tube}
        temp_{shell|tube}_in        actual inlet temp  (°C)
        temp_{shell|tube}_out       actual outlet temp (°C)
        pressure_{shell|tube}_in    actual inlet pressure  (barg)
        pressure_{shell|tube}_out   actual outlet pressure (barg)
        {shell|tube}_flow_scmh      actual SCMH from flow meter
        std_density                 standard density (kg/m³) — e.g. 0.72838 for Bacton gas

    Legacy (kept for back-compat):
        temp_in_{shell|tube} / temp_out_{shell|tube}
        pressure_in_{shell|tube}_bar / pressure_out_{shell|tube}_bar
        pressure_units = "bar_abs" | "barg"
        flow_{shell|tube}_kgh

    Optional for U_actual:
        area_m2, lmtd, f_factor (default 1.0)

    Response
    --------
    {
      "shell": {
        "fluid": "40% ethylene-glycol / water (mass fraction)",
        "coolprop_fluid": "INCOMP::MEG[0.4000]",
        "temp_mean_c": 45.0,
        "cp_kj_kgk": 3.6165,
        "density_kg_m3": 1038.44,
        "viscosity_mPas": 1.4593,
        "conductivity_W_mK": 0.4443,
        "Z_compressibility": null,
        "flow_kgh": 198.0,
        "duty_kw": 3.9781
      },
      "tube": {
        "fluid": "natural-gas — methane approx.",
        "cp_kj_kgk": 2.9126,
        "density_kg_m3": 61.26,
        "Z_compressibility": 0.8489,
        ...
      },
      "u_actual_W_m2K": 284.5,      // only if area_m2 + lmtd + flow provided
      "heat_balance": {
        "shell_duty_kw": 3.978,
        "tube_duty_kw":  3.912,
        "imbalance_kw":  0.066,
        "imbalance_pct": 1.66
      }
    }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    result = {}

    # ── Shell side ─────────────────────────────────────────────────────────────
    try:
        shell = _calc_side(data, "shell")
        if shell:
            result["shell"] = shell
    except (ValueError, KeyError) as e:
        return jsonify({"error": f"Shell side: {e}"}), 422

    # ── Tube side ──────────────────────────────────────────────────────────────
    try:
        tube = _calc_side(data, "tube")
        if tube:
            result["tube"] = tube
    except (ValueError, KeyError) as e:
        return jsonify({"error": f"Tube side: {e}"}), 422

    if not result:
        return jsonify({"error": "Provide at least fluid_shell or fluid_tube"}), 422

    # ── U_actual = |Q| / (A × LMTD × F) ───────────────────────────────────────
    if "area_m2" in data and "lmtd" in data:
        area = float(data["area_m2"])
        lmtd = float(data["lmtd"])
        f_factor = float(data.get("f_factor", data.get("mtd_correction_factor", 1.0)))
        # Prefer shell duty, fall back to tube (use magnitude — direction is fluid-specific)
        shell_duty = (result.get("shell") or {}).get("duty_kw")
        tube_duty  = (result.get("tube")  or {}).get("duty_kw")
        duty_kw    = shell_duty if shell_duty is not None else tube_duty

        if duty_kw is not None and area > 0 and lmtd > 0 and f_factor > 0:
            result["u_actual_W_m2K"] = round((abs(duty_kw) * 1000) / (area * lmtd * f_factor), 3)
            result["u_actual_formula"] = "abs(duty_kw) * 1000 / (area_m2 * lmtd * f_factor)"
            result["f_factor"] = f_factor
        else:
            result["u_actual_W_m2K"] = None
            result["u_actual_note"]  = "flow_kgh, positive area_m2, positive lmtd, and positive f_factor required"

    # ── Heat balance (when both sides have duty) ────────────────────────────────
    # Conservation: shell_duty + tube_duty ≈ 0 (one side absorbs what the other gives up).
    s_duty = (result.get("shell") or {}).get("duty_kw")
    t_duty = (result.get("tube")  or {}).get("duty_kw")
    if s_duty is not None and t_duty is not None:
        imb = abs(s_duty + t_duty)              # ideal HX → 0
        ref = max(abs(s_duty), abs(t_duty), 1e-9)
        result["heat_balance"] = {
            "shell_duty_kw":  s_duty,
            "tube_duty_kw":   t_duty,
            "imbalance_kw":   round(imb, 5),
            "imbalance_pct":  round(imb / ref * 100, 3),
        }

    return jsonify(result)


# ── Mean Bacton Gas composition (HEOS 11-component mixture) ───────────────────
#
# Source: UK Bacton terminal mean composition
# Original 14-component spec:
#   Methane   0.9363  Ethane     0.0325  Propane    0.0069
#   n-Butane  0.0015  IsoButane  0.0012  n-Pentane  0.0009
#   n-Hexane  0.0004  n-Heptane  0.0003  n-Octane   0.0001
#   Benzene   0.0002  Toluene    0.0001  Nitrogen   0.0178
#   Helium    0.0005  CO2        0.0013
#
# CoolProp 7 limitations — missing binary interaction pairs:
#   Toluene  (0.0001) — Toluene/Methane pair absent   → absorbed into n-Heptane
#   Benzene  (0.0002) — Benzene/IsoButane, Benzene/N2 → absorbed into n-Heptane
#   Helium   (0.0005) — Helium/all pairs absent        → absorbed into Nitrogen
#
# Net adjustments (11 components, mole fractions sum = 1.0000):
#   n-Heptane : 0.0003 + 0.0001 + 0.0002 = 0.0006
#   Nitrogen  : 0.0178 + 0.0005          = 0.0183
#
# Error budget: total absorbed = 0.08 mol% — negligible for engineering calcs.
# Validated at 8.85 °C, 76 bar against AspenEDR job 8497.

BACTON_GAS_HEOS = (
    "HEOS::Methane[0.9363]&Ethane[0.0325]&Propane[0.0069]"
    "&n-Butane[0.0015]&IsoButane[0.0012]&n-Pentane[0.0009]"
    "&n-Hexane[0.0004]&n-Heptane[0.0006]&n-Octane[0.0001]"
    "&Nitrogen[0.0183]&CarbonDioxide[0.0013]"
)
BACTON_GAS_REFPROP = BACTON_GAS_HEOS.replace("HEOS::", "REFPROP::", 1)

# Molar masses (g/mol) for glycol mixture — INCOMP backend has no PropsSI('M')
_M_MEG   = 62.068   # ethylene glycol
_M_MPG   = 76.094   # propylene glycol
_M_WATER = 18.015


def _glycol_molar_mass(gprefix: str, mass_frac: float) -> float:
    """Analytical molar mass for glycol/water mixture at given mass fraction."""
    M_glycol = _M_MEG if gprefix == "MEG" else _M_MPG
    # 1/M_mix = w_glycol/M_glycol + w_water/M_water
    inv = mass_frac / M_glycol + (1.0 - mass_frac) / _M_WATER
    return round(1.0 / inv, 4)


def _pressure_abs_bar(pressure_bar: float, pressure_units: str = "bar_abs") -> tuple[float, str]:
    """Return absolute pressure in bar from an absolute or gauge bar input."""
    units = str(pressure_units or "bar_abs").lower().strip()
    if units in ("barg", "bar_g", "gauge"):
        return float(pressure_bar) + 1.01325, "barg"
    if units in ("bar", "bara", "bar_abs", "absolute", "abs"):
        return float(pressure_bar), "bar_abs"
    raise ValueError(f"pressure_units must be 'bar_abs' or 'barg', got {pressure_units!r}")


def _query_props(cp_fluid: str, T_C: float, P_abs_bar: float) -> dict:
    """Query a CoolProp-compatible backend string and return SI-derived properties."""
    T_K = T_C + 273.15
    P_Pa = P_abs_bar * 1e5
    try:
        props = {
            "cp_kj_kgk":         CP.PropsSI("C", "T", T_K, "P", P_Pa, cp_fluid) / 1000,
            "density_kg_m3":     CP.PropsSI("D", "T", T_K, "P", P_Pa, cp_fluid),
            "viscosity_mPas":    CP.PropsSI("V", "T", T_K, "P", P_Pa, cp_fluid) * 1000,
            "conductivity_W_mK": CP.PropsSI("L", "T", T_K, "P", P_Pa, cp_fluid),
        }
    except Exception as e:
        raise ValueError(f"property query failed for '{cp_fluid}' at T={T_C}C, P={P_abs_bar} bara: {e}")

    for key, prop, scale in (
        ("h_kj_kg", "H", 1 / 1000),
        ("molar_mass_g_mol", "M", 1000),
        ("Z_compressibility", "Z", 1),
    ):
        try:
            props[key] = CP.PropsSI(prop, "T", T_K, "P", P_Pa, cp_fluid) * scale
        except Exception:
            props[key] = None
    return props


def _query_props_refprop_first(coolprop_fluid: str, refprop_fluid: str | None,
                               T_C: float, P_abs_bar: float,
                               prefer_refprop: bool = True) -> tuple[dict, str, str | None]:
    """Try REFPROP first, then fall back to the CoolProp fluid string."""
    refprop_error = None
    if prefer_refprop and REFPROP_AVAILABLE and refprop_fluid:
        try:
            return _query_props(refprop_fluid, T_C, P_abs_bar), "REFPROP", None
        except ValueError as e:
            refprop_error = str(e)

    try:
        fallback_note = f"REFPROP fallback reason: {refprop_error}" if refprop_error else None
        return _query_props(coolprop_fluid, T_C, P_abs_bar), "CoolProp", fallback_note
    except ValueError as e:
        if refprop_error:
            raise ValueError(f"{refprop_error}; CoolProp fallback failed: {e}")
        raise


def _fluid_props_single(fluid_name: str, temp_c: float, pressure_bar: float,
                         glycol_pct: float = None, glycol_type: str = "ethylene") -> dict:
    """
    Resolve fluid name, query CoolProp, return property dict.
    Handles mean_bacton_gas, glycol, and all existing _FLUID_ALIASES.
    """
    T_K  = temp_c + 273.15
    P_Pa = pressure_bar * 1e5
    key  = fluid_name.lower().strip()

    # ── Mean Bacton Gas ────────────────────────────────────────────────────────
    if key == "mean_bacton_gas":
        cp_str  = BACTON_GAS_HEOS
        display = "Mean Bacton Gas (11-component HEOS)"
        note    = ("Toluene 0.0001 + Benzene 0.0002 absorbed into n-Heptane; "
                   "Helium 0.0005 absorbed into Nitrogen. "
                   "Total absorbed: 0.08 mol% — negligible for engineering use.")
        molar_mass_g_mol = round(CP.PropsSI("M", "T", T_K, "P", P_Pa, cp_str) * 1000, 4)

    # ── Water-glycol ───────────────────────────────────────────────────────────
    elif key == "water-glycol" or key == "glycol":
        if glycol_pct is None:
            raise ValueError("glycol_pct (mass %) required for glycol fluid")
        frac = float(glycol_pct) / 100.0
        if not (0.01 <= frac <= 0.99):
            raise ValueError(f"glycol_pct must be 1–99, got {glycol_pct}")
        gprefix = _GLYCOL_MAP.get(str(glycol_type).lower(), "MEG")
        gname   = "ethylene" if gprefix == "MEG" else "propylene"
        cp_str  = f"INCOMP::{gprefix}[{frac:.4f}]"
        display = f"{glycol_pct}% {gname}-glycol / water (mass fraction)"
        note    = "INCOMP backend — molar mass computed analytically"
        molar_mass_g_mol = _glycol_molar_mass(gprefix, frac)

    # ── Standard alias / direct CoolProp name ─────────────────────────────────
    else:
        cp_str, display = _resolve_fluid(fluid_name, glycol_pct, glycol_type)
        note = "natural-gas — methane approx." if key == "natural-gas" else None
        try:
            molar_mass_g_mol = round(CP.PropsSI("M", "T", T_K, "P", P_Pa, cp_str) * 1000, 4)
        except Exception:
            molar_mass_g_mol = None

    # ── CoolProp property query ────────────────────────────────────────────────
    try:
        cp_val  = CP.PropsSI("C", "T", T_K, "P", P_Pa, cp_str) / 1000
        rho     = CP.PropsSI("D", "T", T_K, "P", P_Pa, cp_str)
        mu      = CP.PropsSI("V", "T", T_K, "P", P_Pa, cp_str) * 1000
        lam     = CP.PropsSI("L", "T", T_K, "P", P_Pa, cp_str)
    except Exception as e:
        raise ValueError(f"CoolProp failed for '{cp_str}' at T={temp_c}°C, P={pressure_bar} bar: {e}")

    # Compressibility (gases only)
    try:
        Z = round(CP.PropsSI("Z", "T", T_K, "P", P_Pa, cp_str), 5)
    except Exception:
        Z = None

    try:
        h_val = CP.PropsSI("H", "T", T_K, "P", P_Pa, cp_str) / 1000  # J/kg → kJ/kg
        h_kj_kg = round(h_val, 4)
    except Exception:
        h_kj_kg = None

    result = {
        "fluid":             display,
        "coolprop_fluid":    cp_str,
        "temp_c":            temp_c,
        "pressure_bar":      pressure_bar,
        "cp_kj_kgk":         round(cp_val, 5),
        "h_kj_kg":           h_kj_kg,
        "density_kg_m3":     round(rho, 5),
        "viscosity_mPas":    round(mu, 6),
        "conductivity_W_mK": round(lam, 6),
        "molar_mass_g_mol":  molar_mass_g_mol,
        "Z_compressibility": Z,
    }
    if note:
        result["note"] = note
    return result


# ── /fluid_props endpoint ──────────────────────────────────────────────────────

_R_GAS = 8.314472  # J/(mol·K)


def _refprop_bacton_props(T_C: float, P_abs_bar: float) -> dict:
    """
    Direct ctREFPROP property lookup for the 14-component Bacton mixture.
    Matches Job 8541 reference data within 0.003 % on duty.
    """
    if not REFPROP_DIRECT_AVAILABLE:
        raise ValueError(
            "REFPROP direct backend unavailable — required for mean_bacton_gas. "
            f"Check ctREFPROP install and RPPREFIX ({RPPREFIX})."
        )
    # REFPROP DLL is stateful — any CoolProp REFPROP:: call from another fluid
    # resets the active mixture. Re-load the Bacton mixture before each query.
    ierr, herr = _RP.SETUPdll(14, BACTON_RP_FLUIDS, "HMX.BNC", "DEF")
    if ierr > 0:
        raise ValueError(f"REFPROP SETUPdll error {ierr}: {herr}")

    T_K = T_C + 273.15
    P_kPa = P_abs_bar * 100.0
    P_Pa = P_abs_bar * 1e5

    r = _RP.TPFLSHdll(T_K, P_kPa, BACTON_RP_Z)
    if r.ierr > 0:
        raise ValueError(f"REFPROP TPFLSH error {r.ierr}: {r.herr}")

    D_mol_L = r.D
    h_kj_kg = r.h / BACTON_RP_M
    cp_kj_kgk = r.Cp / BACTON_RP_M
    density_kg_m3 = D_mol_L * BACTON_RP_M

    try:
        tr = _RP.TRNPRPdll(T_K, D_mol_L, BACTON_RP_Z)
        viscosity_mPas = tr.eta / 1000.0  # µPa·s → mPa·s
        conductivity_W_mK = tr.tcx
    except Exception:
        viscosity_mPas = None
        conductivity_W_mK = None

    Z = P_Pa / (D_mol_L * 1000.0 * _R_GAS * T_K) if D_mol_L > 0 else None

    return {
        "h_kj_kg":           h_kj_kg,
        "cp_kj_kgk":         cp_kj_kgk,
        "density_kg_m3":     density_kg_m3,
        "viscosity_mPas":    viscosity_mPas,
        "conductivity_W_mK": conductivity_W_mK,
        "molar_mass_g_mol":  BACTON_RP_M,
        "Z_compressibility": Z,
    }


def _fluid_props_backend(fluid_name: str, temp_c: float, pressure_bar: float,
                         glycol_pct: float = None, glycol_type: str = "ethylene",
                         pressure_units: str = "bar_abs",
                         prefer_refprop: bool = True) -> dict:
    """
    REFPROP-first property lookup used by the API endpoints.
    mean_bacton_gas always uses direct ctREFPROP with the 14-component .prf
    composition (no HEOS fallback). Other fluids fall back to CoolProp HEOS.
    Enthalpy is returned as h_kj_kg and enthalpy_units is always kJ/kg.
    """
    key = fluid_name.lower().strip()
    pressure_input_bar = float(pressure_bar)
    pressure_abs_bar, pressure_units_norm = _pressure_abs_bar(pressure_input_bar, pressure_units)

    # ── mean_bacton_gas: REFPROP-direct only, no fallback ────────────────────
    if key == "mean_bacton_gas":
        rp_props = _refprop_bacton_props(temp_c, pressure_abs_bar)
        return {
            "fluid":              "Mean Bacton Gas (14-component .prf, REFPROP direct)",
            "coolprop_fluid":     f"REFPROP::{BACTON_RP_FLUIDS}",
            "refprop_fluid":      f"REFPROP::{BACTON_RP_FLUIDS}",
            "backend_used":       "REFPROP-direct",
            "refprop_available":  True,
            "refprop_version":    REFPROP_VERSION,
            "temp_c":             temp_c,
            "pressure_bar":       round(pressure_abs_bar, 6),
            "pressure_abs_bar":   round(pressure_abs_bar, 6),
            "pressure_input_bar": pressure_input_bar,
            "pressure_units":     pressure_units_norm,
            "enthalpy_units":     "kJ/kg",
            "cp_kj_kgk":          round(rp_props["cp_kj_kgk"], 5),
            "h_kj_kg":            round(rp_props["h_kj_kg"], 4),
            "density_kg_m3":      round(rp_props["density_kg_m3"], 5),
            "viscosity_mPas":     None if rp_props["viscosity_mPas"] is None else round(rp_props["viscosity_mPas"], 6),
            "conductivity_W_mK": None if rp_props["conductivity_W_mK"] is None else round(rp_props["conductivity_W_mK"], 6),
            "molar_mass_g_mol":   round(rp_props["molar_mass_g_mol"], 4),
            "Z_compressibility":  None if rp_props["Z_compressibility"] is None else round(rp_props["Z_compressibility"], 5),
            "note":               "14-component REFPROP composition from shahroz.prf (full Toluene/Benzene/Helium fidelity).",
        }

    note = None
    refprop_str = None

    if key == "water-glycol" or key == "glycol":
        if glycol_pct is None:
            raise ValueError("glycol_pct (mass %) required for glycol fluid")
        frac = float(glycol_pct) / 100.0
        if not (0.01 <= frac <= 0.99):
            raise ValueError(f"glycol_pct must be 1-99, got {glycol_pct}")
        gprefix = _GLYCOL_MAP.get(str(glycol_type).lower(), "MEG")
        gname = "ethylene" if gprefix == "MEG" else "propylene"
        cp_str = f"INCOMP::{gprefix}[{frac:.4f}]"
        display = f"{glycol_pct}% {gname}-glycol / water (mass fraction)"
        note = "INCOMP backend - molar mass computed analytically"

    else:
        cp_str, display = _resolve_fluid(fluid_name, glycol_pct, glycol_type)
        if key == "natural-gas":
            note = "natural-gas - methane approximation"
        if cp_str.startswith("REFPROP::"):
            refprop_str = cp_str
        elif "::" not in cp_str:
            refprop_str = f"REFPROP::{cp_str}"

    props, backend_used, fallback_note = _query_props_refprop_first(
        coolprop_fluid = cp_str,
        refprop_fluid  = refprop_str,
        T_C            = temp_c,
        P_abs_bar      = pressure_abs_bar,
        prefer_refprop = prefer_refprop,
    )

    molar_mass = props.get("molar_mass_g_mol")
    if key == "water-glycol" or key == "glycol":
        gprefix = _GLYCOL_MAP.get(str(glycol_type).lower(), "MEG")
        molar_mass = _glycol_molar_mass(gprefix, float(glycol_pct) / 100.0)

    result = {
        "fluid":              display,
        "coolprop_fluid":     cp_str,
        "refprop_fluid":      refprop_str,
        "backend_used":       backend_used,
        "refprop_available":  REFPROP_AVAILABLE,
        "refprop_version":    REFPROP_VERSION,
        "temp_c":             temp_c,
        "pressure_bar":       round(pressure_abs_bar, 6),
        "pressure_abs_bar":   round(pressure_abs_bar, 6),
        "pressure_input_bar": pressure_input_bar,
        "pressure_units":     pressure_units_norm,
        "enthalpy_units":     "kJ/kg",
        "cp_kj_kgk":          round(props["cp_kj_kgk"], 5),
        "h_kj_kg":            None if props["h_kj_kg"] is None else round(props["h_kj_kg"], 4),
        "density_kg_m3":      round(props["density_kg_m3"], 5),
        "viscosity_mPas":     round(props["viscosity_mPas"], 6),
        "conductivity_W_mK":  round(props["conductivity_W_mK"], 6),
        "molar_mass_g_mol":   None if molar_mass is None else round(molar_mass, 4),
        "Z_compressibility":  None if props["Z_compressibility"] is None else round(props["Z_compressibility"], 5),
    }
    notes = [n for n in (note, fallback_note) if n]
    if notes:
        result["note"] = " ".join(notes)
    return result


@app.route("/fluid_props", methods=["POST"])
def fluid_props():
    """
    POST /fluid_props

    Single-point thermodynamic property lookup via CoolProp.

    Supported fluid names
    ---------------------
    "mean_bacton_gas"   11-component HEOS mixture (UK Bacton terminal, 93.6% CH4)
    "water-glycol"      Ethylene or propylene glycol/water — requires glycol_pct
    "glycol"            Alias for water-glycol
    "water"             Pure water
    "natural-gas"       Methane approximation
    "methane", "ethane", "propane", "nitrogen", "co2", "air"
    Any valid CoolProp backend string (e.g. "R134a", "INCOMP::MPG[0.25]")

    Request body (JSON)
    -------------------
    {
      "fluid":        "mean_bacton_gas",   // required
      "temp_c":       8.85,                // required — mean temperature °C
      "pressure_bar": 76,                  // required — operating pressure bar
      "glycol_pct":   40,                  // required if fluid is glycol
      "glycol_type":  "ethylene"           // optional — "ethylene" | "propylene"
    }

    Response
    --------
    {
      "fluid":             "Mean Bacton Gas (11-component HEOS)",
      "coolprop_fluid":    "HEOS::Methane[0.9363]&...",
      "temp_c":            8.85,
      "pressure_bar":      76.0,
      "cp_kj_kgk":         2.88542,
      "density_kg_m3":     67.26178,
      "viscosity_mPas":    0.012839,
      "conductivity_W_mK": 0.039591,
      "molar_mass_g_mol":  17.2001,
      "Z_compressibility": 0.82888,
      "note":              "Toluene 0.0001 + Benzene 0.0002 absorbed..."
    }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    # Validate required fields
    for required in ("fluid", "temp_c", "pressure_bar"):
        if required not in data:
            return jsonify({"error": f"Missing required field: '{required}'"}), 422

    try:
        result = _fluid_props_backend(
            fluid_name   = str(data["fluid"]),
            temp_c       = float(data["temp_c"]),
            pressure_bar = float(data["pressure_bar"]),
            glycol_pct   = data.get("glycol_pct"),
            glycol_type  = data.get("glycol_type", "ethylene"),
            pressure_units = data.get("pressure_units", "bar_abs"),
            prefer_refprop = bool(data.get("prefer_refprop", True)),
        )
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 422

    return jsonify(result)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
