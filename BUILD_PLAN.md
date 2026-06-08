# HX SENTINEL — BUILD PLAN

## STATUS
Engine validated (7-layer audit: 220/220·44/44·8/8).
Duty accurate 0.003%. Shown to management, being escalated.
GitHub: github.com/Shahrose121/hx-sentinel

## GOLDEN RULE
After ANY change: re-run audit_commercial.py
→ must stay 220/220·44/44·8/8, 8541 = 1148.87 kW
→ if broken, revert.
Keep a stable demo-safe commit always.

---

## NEXT WEEK — FIX & VERIFY
☐ Fix 8471 — re-run EDR, correct design flow (~3405 kg/h),
  re-extract (rebuild_jobdb.py), remove bad_flow flag [data only]
☐ Clarify: does U_ratio use u_clean or u_service_clean?
  Does a clean new unit show sensible value?
☐ Decide tube RhoV²: keep info-only or remove (no TEMA limit;
  tube velocity vs 40 m/s already covers tube side)
☐ Confirm start_all.bat launches clean; demo job ready

---

## ROADMAP

### STAGE 1 — Core ✅ (done bar 8471)

### STAGE 2 — Make it a PRODUCT
☐ Reading history + trend chart (SQLite, U-ratio over time,
  threshold lines, cleaning events) [LOW risk, additive]
☐ Cleaning threshold anchored to U_service per job
  (not arbitrary 0.92/0.82) [MEDIUM risk, test hard]
☐ PDF report (health, trend, recommendation, TEMA) [LOW risk]

### STAGE 3 — Make it UNIQUE
☐ Predicted cleaning date (from fouling trend)
☐ Anomaly detection (sudden faults vs slow fouling)
☐ Customer-adjustable threshold (default U_service)
☐ CSV upload + AI column mapping

### STAGE 4 — Make it INTERNATIONAL
☐ Professional UI polish
☐ Multi-exchanger site dashboard
☐ Gradual limit-based colour (each tied to TEMA/PD 5500)
☐ User guide / documentation
☐ First real exchanger validation → case study

---

## WHAT MAKES IT INTERNATIONAL-GRADE
- Every number defensible (tied to a standard)
- Cleaning logic grounded in design (U_service)
- Professional workflow: store → trend → predict → report
- Never gives a wrong answer (audit-protected)
- Handles messy real data gracefully
- Documented so others trust it

## STRATEGIC (think, don't rush)
- IP / ownership position — clear in your head BEFORE
  next management conversation
- Keep demo ready; live demo beats any document
