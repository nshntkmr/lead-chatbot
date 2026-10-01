# About the MSSP data

- Table: `mssp_tin_all_components_by3_200plus` — 9,419 TINs modeled under the **Medicare Shared Savings Program (MSSP), PY2027**. Every column has an exact definition in the column dictionary (search_columns returns it), and most dictionary entries also carry the workbook's original Excel formula, which is the authoritative description of how a figure was calculated.
- Every row uses the same scenario (the "= value" constants): **ENHANCED track**, prospective assignment, agreement start 2027, BY1–BY3 = 2024–2026 weighted **1/3 each** (note: CMS's standard MSSP weighting is 10% / 30% / 60%; this workbook was configured with equal weights), base-year beneficiary threshold 10, "Historic" trend selection.
- **Four beneficiary categories (Medicare enrollment types):** ESRD, Disabled, Aged/dual (dually eligible), Aged/non-dual. Benchmarks, risk scores and expense are built per category and combined with the assigned-beneficiary proportions.
- Column naming: headline columns are plain (`Projected benchmark`, `Pre-sharing MLR`, …). Workbook cells are named `<Sheet> — <label> [<context>] (<cell>)`, for example `MSSP Shared Saving Losses — Shared savings (B39)`. Source inputs are `SAS … [<year> <cohort>]`, claims are `<year> MSSP claims - <cohort> <category> paid PMPM|USD`.

# MSSP rules this workbook follows

- **Sharing (ENHANCED):** savings are shared at the **final sharing rate = 75%** (quality standard met) once the gross margin is at or above the **minimum savings rate (MSR)**; losses are shared at the **shared loss rate = 40%** once the margin is at or below the **minimum loss rate**. Inside the band there is no shared saving or loss (`Savings or Losses Realized` = "No Shared Savings"; 435 TINs). In this workbook the MSR/MLR band is **±0.5% of the benchmark**.
- **Caps CMS applies but this workbook does not:** ENHANCED shared savings are capped at **20% of the benchmark** and shared losses at **15% of the benchmark**. The workbook's `… - original model` columns are uncapped (`Sharing formulas apply listed caps` = False). `Savings exceed listed 20% benchmark cap` is True for 53 TINs, so their `Shared savings - original model` is overstated. portfolio_metrics reports both the uncapped figure and the capped one.
- **Benchmark construction (per category):** historical expenditure for BY1–BY3, trended to BY3 with a **national–regional blended trend** (the national weight is the ACO's share of its regional assignable population, so for a single TIN the trend is almost entirely regional), risk-adjusted, weighted across base years, then adjusted by the **regional adjustment**, **prior savings adjustment** and **health equity benchmark adjustment (HEBA)**, and finally updated to PY2027 with the **update factor = 1/3 ACPT + 2/3 national–regional blend** (applies to agreement periods starting 2024 or later).
- **Regional adjustment:** the difference between the risk-adjusted regional average and the ACO's historical benchmark, weighted **35%** when the ACO is below the region (positive adjustment) and **15%** when above (negative adjustment), capped at **+5% / −1.5% of the national assignable per-capita FFS amount** (the cap columns hold the dollar caps per category).
- **Prior savings adjustment:** for renewing ACOs with prior savings; in this file `ACO Eligible for Prior Savings Adjustment?` = No for every TIN, so it is 0.
- **HEBA:** eligible when the ACO's share of dual-eligible / Part D LIS beneficiaries exceeds **15%** in this workbook (1,837 TINs eligible; CMS's published threshold is 20%, so check which is intended). The adjustment is a per-beneficiary dollar amount scaled so that HEBA plus any positive regional or prior-savings adjustment stays within 5% of the national per-capita amount.
- **Risk adjustment:** CMS-HCC risk ratios relative to BY3, capped at **±3%** per category (`Risk Ratio Cap [D]` = 1.03). About a third of TINs hit the cap for the Disabled category.
- **Financial guarantee / repayment mechanism:** the workbook uses **0.5% × BY3 cost**. (CMS's repayment-mechanism rule is based on the lesser of a percentage of benchmark or of participant revenue; treat the workbook figure as the modeler's assumption.)
- **Quality:** `ACO Quality Score` = 1 and the quality standard is met for every TIN, so the full 75% sharing rate applies.
- **Not modeled:** 2% sequestration on shared savings payments; the ENHANCED caps (above); prepaid shared savings or advance investment payments.
- **CY2027 rulemaking:** the July 2026 PFS proposed rule would change MSSP for agreement periods starting 2027 — regional adjustment weight for ENHANCED 50% → 35%, prior-savings scaling 50% → 75%, a risk-adjusted 5% cap on positive adjustments, ACPT guardrails, and BASIC E sharing 50% → 60%. These were proposals (comment deadline September 2026); say so if asked and don't present them as final.

# Workbook identities (verified against the data)

- `Projected benchmark` = `Projected annual benchmark per person year` × `Projected person years`
- `Projected expenditures` = `Projected annual expense per person year` × `Projected person years`
- `Gross margin before sharing` = benchmark − expenditures; `Pre-sharing MLR` = expenditures ÷ benchmark
- `Shared savings - original model` = 0.75 × margin when margin ≥ 0.5% × benchmark; `Shared losses signed - original model` = 0.40 × margin when margin ≤ −0.5% × benchmark; otherwise 0. `Net shared result - original model` is their sum. `Post-sharing MLR - original model` = 1 − net shared ÷ benchmark.
- Per category: benchmark $ = `MSSP Updated Benchmark — Updated Benchmark Expenditures ($) — <cat> [PY2027]` × `MSSP Shared Saving Losses — Projected cohort person years — <cat> [PY2027]`; expense $ = `MSSP Shared Saving Losses — Projected expense — <cat> [PY2027]` × the same person years.
- Financial guarantee = `MSSP Shared Saving Losses — BY3 Cost [PY2027] (B45)` × 0.5%.

## Calculation chain (sheets in order)

1. `SAS …` source inputs (beneficiaries, member months, paid, risk by year and category), `National …` / `Assignable …` reference data, PROSP / PROSP COUNTY assignment inputs.
2. `MSSP Trend Factor` — national and regional trend factors and weights, blended trend.
3. `MSSP Historical Benchmark` — per-category expenditures by base year, trended, risk-adjusted, weighted; `Historical Benchmark Before Regional Adjustment, Prior Savings Adjustment, or Health Equity Benchmark Adjustment`.
4. `MSSP Regional Adjustment`, `MSSP Prior Savings Adj`, `MSSP Health Equity Adj`.
5. `MSSP PY Risk` — PY2027 risk ratios and caps.
6. `MSSP ACPT` — Office of the Actuary growth factors, `MSSP Updated Benchmark` — update factor and `Updated Benchmark ($) [PY2027] (D44)` per person-year.
7. `MSSP Shared Saving Losses` — projected person years, expense and benchmark $, MSR/MLR, sharing, financial guarantee. The plain headline columns at the start of the table repeat the key results.

# Answering tips (MSSP)

- A "savings" question usually means `Gross margin before sharing` (before sharing) or `Net shared result - original model` (after the 75% / 40% sharing, uncapped). Say which, and mention the cap when `Savings exceed listed 20% benchmark cap` is True.
- Watch the **MLR collision**: `Pre-sharing MLR` is expense ÷ benchmark; `Minimum Loss Rate (%)` is the −0.5% threshold. Users almost always mean the former.
- `MSSP Shared Saving Losses — Savings or Losses Realized` has three values: Saving, Losses, No Shared Savings.
- `Qualifying TINs sharing this NPI - count` > 1 (107 NPIs) means the TIN shares its source population with other TINs; summing them double-counts.
- Weight averages by `Projected person years`. Beneficiary counts: `Projected beneficiaries` (PY2027) vs `BY3 aligned beneficiaries - eligibility` (2026 base-year count) are different bases.
- Claims columns: `<2025|2026> MSSP claims - <ESRD|Disabled|Aged dual|Aged nondual|TIN total> <Inpatient|Hospital outpatient|SNF|HHA|DME|Physician/carrier|Hospice> paid <PMPM|USD>`; 2026 dollars cover Jan–May only.
