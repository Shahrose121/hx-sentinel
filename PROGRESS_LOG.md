# HX SENTINEL — PROGRESS LOG

One line per completed item. Newest at top.

## 2026-06-16
- 8471 flow fix — root cause: EDR saved flow scalars in kg/s (SI) while all other jobs use kg/h; batch extraction read raw XML value without unit conversion, storing 0.9509 (kg/s) as 0.9509 "kg/h" — 3580x too low. Fix: (1) added flow_unit_to_kgh=3600 to job 8471 DB entry; (2) rebuild_jobdb.py updated to apply per-job flow multiplier (FLOW_KEYS, flow_mult); (3) EDR re-run 100/100 OK, U_clean=500.85 kW/m²K restored, tube_flow_design_kgh now 3423.4. Audit 220/220·44/44·8/8, 0 hard failures. bad_flow_source flag removed.

## 2026-06-08
- Health logic fixes — corrected health-state calculation.
- Duty / pressure-energy fix — energy balance now accurate to 0.003%.
- Allowable-dP leak fix — closed allowable pressure-drop leak.
- Pressure unit clarification — units resolved/consistent throughout.
- TEMA RhoV² shell-side fix — RhoV² now correctly applied shell side.
- Cache-buster — added to force fresh loads in UI/data path.
- Audit suite — audit_commercial.py validating 220/220·44/44·8/8 (8541 = 1148.87 kW).
