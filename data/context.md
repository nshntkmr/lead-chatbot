# About these workbooks

- Each dataset is a **TIN-level financial projection for Performance Year (PY) 2027** produced by a modeling workbook. Each row is one TIN (tax ID) with its organization NPI and name, modeled as if the TIN were a standalone ACO. The numbers are projections, not CMS settlement results.
- "200plus" in the file names means only TINs with at least 200 beneficiaries are included.
- TIN and NPI are identifiers stored as text. Never sum or average them. A few NPIs are shared by 2–4 TINs; their populations overlap, so adding such TINs together double-counts.
- Sign convention everywhere: savings positive, losses negative (benchmark − expense).
- **MLR in this app means expense ÷ benchmark** (a medical-loss-ratio style figure; the workbook columns are `Pre-sharing MLR …`). It is **not** the MSSP "Minimum Loss Rate", which also abbreviates to MLR and appears in the MSSP data as `Minimum Loss Rate (%)`. If a user says "MLR", assume expense ÷ benchmark unless they clearly mean the MSSP threshold.
- PBPM = per beneficiary per month and PMPM = per member per month (used interchangeably). Per-person-year = annual amount per beneficiary year = PBPM × 12. Never sum per-member figures across TINs; weight them by person years or member months. Dollar columns can be summed.
- The column dictionary (`MSSP_TIN_Column_Dictionary.csv`) is written for the MSSP workbook, where every column has an exact definition. For LEAD, about 245 columns link to a definition by name pattern; the rest are explained by the LEAD notes. Quote the dictionary definition when search_columns returns one.
- No geography (state/county) columns exist in either extract, so "TINs in Texas" cannot be answered; say so and offer to filter by organization name instead.
- `2026 … prevalence rate - <condition>_benes` columns hold TIN-level chronic-condition and utilization prevalence fractions (cad, hyt, afib, hyperlip, diab, hf, ckd1–5, snf_util, ip_util, hha_util, hospice_util).
- The "BY3 = 2026" year is a partial year in both workbooks: Jan–May claims (5 exposure months) annualized × 2.4, then × 1.0612 (IBNR 1.02 × completion 1.022 × seasonality 1.018), blended 30% observed 2026 / 70% trended history.

# Portfolio questions (groups of TINs)

- "I have these TINs" means the combined picture as if the TINs formed one ACO. Use **portfolio_metrics** (saves the list as the chat's working portfolio), **portfolio_suggest** for "which TINs should I add or drop to reach X%", and **compare_programs** for "is this TIN/portfolio better in LEAD or MSSP".
- **Combined MLR = Σ expense $ ÷ Σ benchmark $.** Never average TIN MLRs.
- Room under a target: `target × benchmark $ − expense $` per TIN (`room_under_target_usd`; a negative value is that TIN's contribution to the target gap). A group meets the target when the sum is ≥ 0. That is how portfolio_suggest picks the fewest TINs to add or remove.
- Stress tests: portfolio_metrics with `expense_change_pct` / `benchmark_change_pct` rescales every TIN's expense or benchmark (a what-if on trend, not a re-run of the model).
- For these users (actuaries, CFO/CEO/CSO) lead with combined MLR, benchmark $, margin $ and person-years, say whether the target is met, and put per-TIN detail in a table. State approximations (mixed classifications, TINs sharing an NPI, caps not applied in the workbook).

# Abbreviations

| Term | Meaning |
|---|---|
| BY / PY | base year / performance year |
| ACPT | Accountable Care Prospective Trend (CMS Office of the Actuary projection used in benchmark updates) |
| MSR / MLR (MSSP sense) | minimum savings rate / minimum loss rate — thresholds before savings or losses are shared |
| HCC | hierarchical condition category (risk adjustment) |
| IBNR | incurred but not reported |
| PQEM | primary care qualified evaluation & management services (claims-based assignment) |
| SAHS | significant, anomalous and highly suspect billing |
| HEBA | Health Equity Benchmark Adjustment (MSSP) |
| REA / PSA | Regional Efficiency Adjustment / Prior Savings Adjustment (LEAD) |
| PCC / EPCC / TCC / APO | LEAD capitation options |
