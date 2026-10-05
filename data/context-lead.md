# About the LEAD data

- Table: `lead_tin_all_components_by3_200plus` — 11,865 TINs modeled under the **CMS LEAD model, PY2027**.
- Every row uses the same scenario (the "= value" constants): Prospective alignment, a Renewing ACO, predecessor program ACO REACH, and the **Global** risk arrangement. Say so when an answer depends on it; the discount and corridors below are the Global ones.
- For the `Settlement | …` columns, a positive value is paid to the ACO and a negative value is owed back to CMS.
- LEAD Global has **no minimum savings or loss rate and no "no shared savings" band** — sharing starts at the first dollar. Those are MSSP concepts (the MSR / minimum-loss-rate band, "No Shared Savings" status). Asked about them here, say in two or three sentences that LEAD has no such band and that the figure lives in the MSSP dataset, which needs a new chat on MSSP; do not substitute a LEAD count.
- **19 of the 11,865 rows have a $0 benchmark and $0 expense** (2027 alignment unavailable, no modeled population). Their `Pre-sharing MLR = expense / benchmark` is stored as 0, not blank, so they would pass any "MLR at or under X%" test. Add `"Total benchmark" > 0` whenever a per-TIN MLR is tested, ranked or summarised (counts against a threshold, medians, distributions). Plain TIN counts by category and dollar totals keep all rows — the 19 add $0. Asked how many TINs there are, give both figures: 11,865 rows, of which 11,846 have a benchmark.

# Column-name traps in the LEAD extract (details are in the column notes that search_columns returns)

- About 100 columns are **worksheet label cells**, not data: they hold a caption or a year. The worst-named ones are `ESRD` (= 2024), `High Needs (HN)` (= 2025), `Risk Score [Aged & Disabled (A&D)]` (= 2026), `Beneficiary Counts [...]`, `Renormalization Factors - [...]`, `Trend Factor`, `Historical Benchmark Calculation`. They are listed separately in the schema; never use them as data.
- `Benchmark discount` is the discount **rate** (0.03 or 0.0175), not an amount. It is applied as `Benchmark PBPM after discount` = `Benchmark PBPM before discount` × (1 − `Benchmark discount`), which holds in every row; state this formula when asked what the discount is or how it is applied. `Administrative add-on` is total **dollars** (1.5% × benchmark × person years × 12 for High Spending TINs), although it sits among PBPM columns.
- `Settlement | total monies owed`: positive = CMS pays the ACO, negative = the ACO owes CMS. It is dominated by the enhanced PCC repayment, so a TIN with savings can still show a negative total.
- Several columns are exact duplicates (same values in every row): `Spending classification` = `ACO spending classification`; `Benchmark PBPM after discount` = `Benchmark PBPM after discount and earned quality` and `Quality withhold PBPM` = `Earned quality withhold PBPM` (quality score = 1); `Retained savings or losses after risk corridors` = `Settlement | shared savings or losses`; `BY3 aligned beneficiaries (2026 eligibility count)` = `Total cohort beneficiaries | 2026`; `Expenditure PBPM | cohort | BYn` = `Assigned expenditure PBPM | cohort | year`; `Churn calculation | …` = the `Beneficiaries` / `Eligible member months` columns. Pick one and say which.
- `Exposure retention factor (workbook label: Churn Rate)` is a **retention** share (median 0.97), despite the workbook label.
- Raw cells: `PROSP__*` row 3 are the TIN's own inputs (most are duplicates of `Treated beneficiaries / member months / Raw risk [year cohort]`); `Assignable__*` and `National [LEAD Assignable!…]` are national reference constants; `PQEM__*` are REACH capitation reference constants behind the Base PCC fraction. Prefer the named columns the notes point to.
- `Input notes` says when a TIN's NPI population also maps to other TIN keys — those TINs must not be added together.
- `Input notes` also carries data-quality flags for 910 of the 11,865 TINs (blank for the rest): no 2024 and/or 2025 assigned-provider source record (the model's missing-year handling was used, so the projection rests on less history), 2027 alignment unavailable (beneficiaries projected from the 2024–2026 trend), or a blank ESRD risk score. Whenever an answer lists named TINs or singles one out (a name search, a short ranking, the best or weakest of a group), include `Input notes` in the query and mention any flag in one line next to that TIN, in plain words. Say nothing when the notes are blank, and do not add it as a table column unless asked.
- Dictionary links: the column dictionary describes the MSSP workbook; LEAD columns link to it only by matching names, never by cell position, so its definitions are indicative for LEAD and the column notes take precedence.

# LEAD model: what CMS published

Sources: CMS LEAD Request for Applications, LEAD Technical FAQs, PY2027 Alignment & Finance Methodology paper (July 2026), LEAD Risk Adjustment memo, and the LEAD Payment fact sheet.

- **LEAD = Long-term Enhanced ACO Design.** It's a voluntary 10-year CMS Innovation Center ACO model running **Jan 1, 2027 – Dec 31, 2036**, and the successor to ACO REACH. ACOs join as whole TINs (REACH used TIN-NPIs). The benchmark is **not rebased** during the 10 years.
- **Risk options**
  - **Global:** up to 100% of savings and losses. Only Global ACOs can take Total Care Capitation and a positive Regional Efficiency Adjustment, and only Global ACOs get the benchmark discount.
  - **Professional:** up to 60% of savings and 50% of losses, per the PY2027 paper. (Earlier FAQs said 50% savings.) Professional ACOs have no discount.
- **Beneficiary categories (cohorts)**
  - **AD** = Aged & Disabled.
  - **ESRD** = End-Stage Renal Disease.
  - **HN** = High Needs. A beneficiary qualifies by meeting at least one criterion: a mobility-impairment diagnosis, frailty, risk score ≥ 3.0 (A&D) or ≥ 0.35 (ESRD), a risk score of 2.0–3.0 with 2+ unplanned admissions, or 45+ SNF days. Status is assessed quarterly, and "once High Needs, always High Needs".
- **Alignment:** prospective or hybrid, claims-based using PQEM (primary care qualified E&M) services, plus voluntary alignment.
- **Base years for PY2027:** BY1 = CY2024, BY2 = CY2025, BY3 = CY2026. Renewing ACOs weight them 1/3 each; newly entering ACOs weight them 10% / 30% / 60%.
- **Benchmark update:** a three-way blend. Two-thirds is the national–regional two-way trend, and one-third is the Accountable Care Prospective Trend (**ACPT**, from CMS Office of the Actuary projections). The ACPT has guardrails around the two-way trend: +0.3% / −0.2% in PY2027, widening in later years.
- **Risk adjustment**
  - A&D: CMMI Prospective Model V1, based on CMS-HCC V28.
  - High Needs: CMMI Concurrent Model V2.
  - ESRD: PY2023 V24 ESRD CMS-HCC.
  - Risk-score growth is capped symmetrically at **3%** for A&D and ESRD and **4%** for High Needs, with BY3 as the reference year.
- **Spending designation:** each ACO is classed **Higher-spending** or **Lower-spending** against regional FFS spending.
  - Higher-spending ACOs get a **1.5% administrative add-on**. The Global discount for them is **1.75%** in PY2027, rising to 3% by PY2032.
  - Lower-spending Global ACOs have a flat **3%** discount and can get a **Regional Efficiency Adjustment** of 50% of the risk-adjusted difference, capped at 3% for renewing former-MSSP ACOs and 5% for others.
- **Prior Savings Adjustment:** 50% of prorated prior savings, capped. An ACO gets the higher of REA or PSA, never both.
- **Quality withhold:** **3%** of the benchmark, earned back based on quality performance.
- **Capitation**
  - **Base PCC** (Primary Care Capitation) plus **Enhanced PCC**, which brings the total up to about 7% of the benchmark (at least 2%). Enhanced PCC is repaid at settlement.
  - **TCC:** Total Care Capitation, Global only.
  - **NPCC / APO:** non-primary-care capitation and the Advanced Payment Option.
- **Other adjustments:** SAHS codes (significant, anomalous and highly suspect billing) are 100% excluded from spending. Skin substitutes are 65% excluded. 2% sequestration applies to shared savings and losses.

# How this workbook implements it (constants in the data)

- **BY3 (2026) is a partial year**
  - Claims cover Jan–May (5 exposure months), annualized × 2.4.
  - Adjusted × 1.0612 = IBNR 1.02 × completion 1.022 × seasonality 1.018.
  - Blended as 30% partial-year actual expense + 70% historically trended expense.
- **Trends:** the two-way trend is credibility-weighted between TIN and national trends. The population scales are ESRD 200, HN 1,000 and AD 3,000. Trend bounds are 0.8–1.2.
- **Three-way update weights:** historical 2/3, ACPT 1/3. The ACPT assumptions are ESRD 1.0734, HN 1.0851 and AD 1.0665.
- **Risk ratio bounds:** 0.97–1.03 for AD and ESRD, and 0.96–1.04 for HN (the 3% and 4% caps).
- **Spending classification:** `ACO spending classification` / `Spending classification` hold "High Spending ACO" or "Low Spending ACO".
- **Discounts and adjustments:** the discount is 1.75% for high-spending and 3% for low-spending ACOs. The admin add-on is 1.5% for high-spending ACOs. The positive regional cap is 3% (renewed from MSSP) or 5% (other). The prior-savings scaling is 50% with a 5% cap. In this file, `Prior savings eligibility | Final` = No, so the PSA is 0.
- **Quality:** the withhold is 3%, and the quality score is 1, so the full withhold is earned back.
- **Global risk corridors** (share of savings or losses the ACO keeps, by band of the benchmark):

  | Band | ACO keeps |
  |---|---|
  | 0–15% | 100% |
  | 15–35% | 50% |
  | 35–50% | 25% |
  | >50% | 10% |

- **Professional risk corridors** (not the scenario used in this file):

  | Band | ACO keeps |
  |---|---|
  | 0–10% | 60% |
  | 10–15% | 35% |
  | 15–20% | 15% |
  | >20% | 5% |

- **PCC:** the Base PCC fraction is 3.164%, from REACH PQEM paid data for 2025–2026. The Enhanced PCC fraction is 3.836%, bringing the combined target to 7%.
- **Financial guarantee:** 4% × annualized BY3 cost.

## Calculation chain (column families in order)

1. Source inputs: `Raw…` / `Treated…` beneficiaries, member months, risk and paid by `[year cohort]`, plus the `PROSP__*`, `Assignable__*`, `PQEM__*` and `PROSP_COUNTY__*` raw cells.
2. `Expenditure PBPM | cohort | BYn`, then `National-regional blended trend to BY3`, then risk adjustment.
3. `Weighted historical benchmark PBPM | cohort | BYn / Total`, then `Historical benchmark PBPM before ACO-specific adjustment`.
4. `Regional adjustment before cap / after cap | cohort | BY3` and prior savings, then `Historical benchmark PBPM after ACO-specific adjustment`.
5. `Benchmark update trend | cohort | …`, then `Updated benchmark PBPM | cohort | PY2027`.
6. `Total updated benchmark PBPM before discount and quality`, then `Benchmark discount`, then `Benchmark PBPM after discount`, then `Quality withhold PBPM` / `Earned quality withhold PBPM`, then `Benchmark PBPM after discount and earned quality`.
7. `Projected expense PBPM | cohort | PY2027` and `Projected expense PBPM` (total). `Pre-sharing MLR = expense / benchmark`.
8. `Gross margin / total savings before risk corridors` (in USD), then `Gross savings or losses in corridor | Corridor 1–4`.
9. `Settlement | shared savings or losses`, `| sequestration`, `| enhanced PCC repayment`, `| APO adjustment` and `| high-performers pool incentive`, then `Settlement | total monies owed`.
10. `Post-sharing MLR`, `Financial guarantee amount`, and `Person years by cohort | cohort | PY2027`.

# LEAD portfolio math (verified against the data)

- benchmark $ = `Benchmark PBPM after discount and earned quality` × `Person years after exposure adjustment` × 12 (equals `Total benchmark`)
- expense $ = `Projected expense PBPM` × person years × 12
- gross margin $ = benchmark $ − expense $ (equals `Gross margin / total savings before risk corridors`)
- **MLR 85% = savings of 15% of benchmark**, exactly the top of Global corridor 1 (savings up to 15% are kept 100%). Read the direction carefully: a TIN with an MLR between 85% and 100% has savings of *less than* 15% of benchmark, so all of its savings are *inside* corridor 1 and kept in full; only a TIN with an MLR *below* 85% has savings beyond corridor 1. (Losses mirror this: MLR up to 115% is inside corridor 1.) Above 15% the ACO keeps only 50%, then 25%, then 10%, so there is little financial reason to push a Global ACO's MLR much below 85%. Most TINs sit well above 85% (check the distribution with a query when a target looks ambitious).
- portfolio_metrics also returns the financial guarantee (4% × annualized BY3 cost), the quality withhold at risk (3% of benchmark, fully earned back here because the quality score is 1), enhanced PCC repayment, and the shared loss in an illustrative scenario where gross losses equal the whole benchmark (15% + 10% + 3.75% + 5% = 33.75% of benchmark for Global; a scenario, not a maximum — see below).
- Cohort figures from portfolio_metrics are on the same discounted basis as the combined figures (the workbook's `Updated benchmark PBPM | cohort | PY2027` is pre-discount; the tool scales it). If you compute cohort MLRs yourself with SQL, apply `Benchmark PBPM after discount and earned quality ÷ Benchmark PBPM before discount`, otherwise cohort MLRs come out ~3% too low and don't reconcile to the total.
- When you report cohort benchmarks or cohort MLRs, say in one line that they are derived: the workbook's pre-discount cohort benchmarks with each TIN's benchmark discount allocated pro rata, so they reconcile to the portfolio total. With a target, portfolio_metrics also returns each cohort's `room_under_target_usd` (target × cohort benchmark − cohort expense); these sum to the portfolio's own `room_under_target_usd`, so report a cohort's negative value as its "contribution to the target gap" in dollars instead of characterising the cohort.
- Sensitivity to the discount rate: a TIN's benchmark at another rate = its benchmark × (1 − new rate) ÷ (1 − its current `Benchmark discount`), because the quality score is 1 (the whole withhold is earned back) and the discount is the last step before `Benchmark PBPM after discount and earned quality`. Apply it only to the rows whose current rate is the one being changed (3% = Low Spending, 1.75% = High Spending); projected expense does not move. Corridor sharing and sequestration can be recomputed from the new margin; the enhanced PCC repayment, financial guarantee and spending classification are not re-derived, so no projected net settlement follows from it.
- Under a stress test the cohort figures are rescaled the same way as the TIN rows, so they can be quoted for the scenario; the enhanced PCC repayment, financial guarantee and quality withhold stay at base case.
- Sequestration in this workbook is 2% of the gross savings or loss before the corridors (`Settlement | sequestration` = −2% × |`Gross margin / total savings before risk corridors`| in every row), negative for gains and for losses alike. It equals 2% of the shared amount only while the result is within the first corridor.
- The settlement lines apply the corridors and sequestration once to the pooled margin (one ACO). Summing each TIN's standalone settlement gives a different figure when some TINs gain and others lose, because sequestration reduces gains and increases losses; portfolio_metrics returns both.
- `shared_loss_if_loss_equals_benchmark_usd` is an illustrative scenario (loss = 100% of benchmark through the corridors = 33.75% of benchmark), not a maximum — the LEAD corridors keep sharing 10% beyond that with no ceiling. Call it a scenario, never "the worst case".
- `Settlement | total monies owed` and the portfolio settlement line are the workbook's projected settlement balance; say "projected" — a negative figure means the model projects the ACO would owe CMS, not that it definitively does.
- Distinct NPIs across a portfolio rule out the double-counting the `Input notes` warn about; they do not prove zero beneficiary-level overlap between organizations (the data can't show that).
- Approximation to state: each TIN's benchmark uses its own spending classification (discount 1.75% vs 3%, regional adjustment). A real ACO gets one classification for the whole population, so mixed-class portfolios are approximate.

# Answering tips (LEAD)

- **Beneficiary counts have two bases — say which when a question filters or ranks on a beneficiary count.** `Assigned beneficiaries` is the PY2027 count the model uses for person-years (= `2027 aligned beneficiaries` where CMS supplied it; for 223 TINs it is the model's own trend projection — `2027 beneficiary projection basis` says which). `Total cohort beneficiaries | 2026` (= `BY3 aligned beneficiaries (2026 eligibility count)`) is the 2026 base-year count behind the "200plus" file filter. They can differ a lot for growing practices (e.g. 487 in 2026 vs 1,331 assigned for 2027), so "TINs with at least 1,000 beneficiaries" gives a different list on each basis. Default to `Assigned beneficiaries` for PY2027 questions, label the column "PY2027 assigned beneficiaries" in tables, and mention the 2026 alternative in one line. This applies only when the beneficiary count drives the filter or the ranking; a list ranked or filtered on benchmark, MLR or anything else is unaffected by the choice, so do not add a beneficiary column or this caveat there.
- **Prevalence columns** (`2026 prevalence rate - <condition>_benes`) come from a separate 2026 source joined by treating its NPI-org id as the TIN (`2026 prevalence join status`); 102 TINs have no match. The source denominator is not in the file (`… source total_benes` is normalized to 1.0), so the prevalence population may differ from the model's aligned population. Near-100% home-health prevalence for mobile / house-call practices is plausible, not a data error — describe it as far above the median without implying bad data. When filtering on another column, report the missing-prevalence count *within that filter*, not the dataset-wide 102.
- **Thresholds and comparisons:** test "at or below X%" on the unrounded value (90.14% is not ≤ 90%). When comparing a top-N group with "the rest", exclude the top N from the rest. Two pooled MLRs do not show whether a relationship exists; if the user asks about a relationship, compute pooled MLR by decile (or a correlation) across the eligible TINs and report that instead.
- A "savings" question usually means `Gross margin / total savings before risk corridors` (before sharing) or `Settlement | shared savings or losses` (after corridors). Say which one you used.
- Weight averages by `Person years after exposure adjustment` or by member months.
- Claims columns follow `<year> <cohort> <category> claims cost (PMPM | USD …)`. Cohorts: AD, HN, ESRD, "TIN total". Categories: IP, Hospital OP, SNF, HHA, Hospice, DME, Physician-carrier. 2026 dollars cover Jan–May only.
- The `<Sheet>__<Cell>` columns (for example `PROSP__G3`) are raw cells from a workbook sheet; search_columns shows what each holds.
