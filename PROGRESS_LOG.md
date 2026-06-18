# HX SENTINEL — PROGRESS LOG

One line per completed item. Newest at top.

## 2026-06-18 (Area ratio fix)
- Area ratio replaced — ML regressor removed, replaced with physics calculation: design_ar = u_clean/u_service_clean matches EDR exactly, current_ar = u_clean/U_actual tracks live fouling. Verified against job 8497 (design_ar = 1.295, current_ar = 1.276).
- Amber flag added when current AR exceeds design AR — dashboard health panel ("Exceeding design fouling allowance").
- PDF report updated with both AR values — Current AR and design AR shown in the health verdict box, with the same amber flag when exceeded.
- ML maintenance_class prediction untouched — only the area-ratio number changed. Audit 220/220·44/44·8/8 unchanged (display-only change, audit_commercial.py tests api.py pipeline, not dashboard.html).

## 2026-06-16 (PDF report)
- PDF export — Generate Report button (disabled until analysis run). jsPDF 2.5.1 via CDN. Single-page A4: navy header bar with HX Sentinel + P&L branding; health verdict box colour-coded by class (green/amber/orange/red); Key Results table (duty, duty loss, U actual, U ratio, shell/tube outlet temps with delta); TEMA Compliance table with green PASS / red FAIL badges per row; trend chart embedded from canvas; recommendation box; footer with REFPROP disclaimer. Button enables after first Run Analysis; report snapshot captured in lastReport object. No calc logic changed. Audit 220/220·44/44·8/8. Pushed 36a168e.

## 2026-06-16 (Stage 2)
- Reading history + trend chart — additive only. New: SQLite readings.db with 18-column readings table; POST /save_reading stores one row per analysis; GET /history/<job_id> returns last 100 oldest-first. Dashboard: after Run Analysis success, result is POSTed non-blocking; history fetched and replaces trend chart (real timestamps on X, U_ratio on Y 0.5-1.1, points coloured by health_class, star markers where U_ratio jumps >=0.05 = cleaning event, threshold lines at 0.85/0.75). "✓ Reading saved" confirmation shown 3 s. Chart init starts empty. Audit 220/220·44/44·8/8 unchanged. Pushed b643463.

## 2026-06-16 (8471 fix)
- 8471 flow fix — root cause: EDR saved flow scalars in kg/s (SI) while all other jobs use kg/h; batch extraction read raw XML value without unit conversion, storing 0.9509 (kg/s) as 0.9509 "kg/h" — 3580x too low. Fix: (1) added flow_unit_to_kgh=3600 to job 8471 DB entry; (2) rebuild_jobdb.py updated to apply per-job flow multiplier (FLOW_KEYS, flow_mult); (3) EDR re-run 100/100 OK, U_clean=500.85 kW/m²K restored, tube_flow_design_kgh now 3423.4. Audit 220/220·44/44·8/8, 0 hard failures. bad_flow_source flag removed.

## 2026-06-08
- Health logic fixes — corrected health-state calculation.
- Duty / pressure-energy fix — energy balance now accurate to 0.003%.
- Allowable-dP leak fix — closed allowable pressure-drop leak.
- Pressure unit clarification — units resolved/consistent throughout.
- TEMA RhoV² shell-side fix — RhoV² now correctly applied shell side.
- Cache-buster — added to force fresh loads in UI/data path.
- Audit suite — audit_commercial.py validating 220/220·44/44·8/8 (8541 = 1148.87 kW).
