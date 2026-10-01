"""Generate data/column_notes-lead.csv: definitions for LEAD columns whose names are confusing.

Raw-cell mappings below were established by value fingerprinting (a raw cell is marked a duplicate
only when its values are identical to the named column in every row) and arithmetic checks; see
the chat/README for the verification. Re-run after a LEAD extract changes:  python -m scripts.make_lead_notes
"""
import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "column_notes-lead.csv"
rows: list[tuple[str, str, str]] = []   # (column_or_pattern, kind, definition)


def add(col, kind, definition):
    rows.append((col, kind, definition))


# ---------------------------------------------------------------- label cells (not data)
LABELS = {
    "Renormalization Factors - [Assigned]": "Year header (2023) of the risk-renormalization table; not a factor.",
    "Renormalization Factors - [Assignable]": "Year header (2024) of the risk-renormalization table; not a factor.",
    "Renormalization Factors - [REACH]": "Year header (2025) of the risk-renormalization table; not a factor.",
    "Renormalization Factors - [LEAD Parameters!E26]": "Year header (2026) of the risk-renormalization table; not a factor.",
    "Renormalization Factors - [LEAD Parameters!F26]": "Year header (2027) of the risk-renormalization table; not a factor.",
    "Historical_Benchmark__B4": "Year header (2024 = BY1) of the Historical Benchmark sheet.",
    "Historical_Benchmark__C4": "Year header (2025 = BY2) of the Historical Benchmark sheet.",
    "Historical_Benchmark__D4": "Year header (2026 = BY3) of the Historical Benchmark sheet.",
    "Historical Benchmark Calculation": "Section caption cell; its value 'BY1' is the first column header of that table.",
    "Claims Alignment Benchmark Calculation": "Section caption cell; value 'BY3' is a column header.",
    "Total Savings/Losses Calculation": "Section caption cell; value 'PY2027' is a column header.",
    "Regional Adjustment Calculation": "Section caption cell.",
    "Prior Savings Adjustment Calculation": "Section caption cell; value 'PY Corresponding to BY1' is a column header.",
    "Trend Factor": "Section caption cell; value 'BY1' is a column header.",
    "Trend Factor / BY1": "Section caption cell; value 'BY3' is a column header.",
    "Trend_Factor__B3": "Year header (2024) of the Trend Factor sheet.",
    "Trend_Factor__C3": "Year header (2025) of the Trend Factor sheet.",
    "Trend_Factor__D3": "Year header (2026) of the Trend Factor sheet.",
    "Trend_Factor__F3": "Year header (2027) of the Trend Factor sheet.",
    "[B]Eligible Months [Benes -]": "Year header (2024) of the churn table (beneficiaries block).",
    "[B]Eligible Months [LEAD Historical Benchmark!H11]": "Year header (2025) of the churn table (beneficiaries block).",
    "[B]Eligible Months [Member Months -]": "Year header (2024) of the churn table (member-months block).",
    "[B]Eligible Months [LEAD Historical Benchmark!J11]": "Year header (2025) of the churn table (member-months block).",
    "ESRD": "Despite the name, a year header cell (2024) of the churn table. For ESRD data use the 'Beneficiaries | ESRD | …', 'Expenditure PBPM | ESRD | …' etc. columns.",
    "High Needs (HN)": "Despite the name, a year header cell (2025) of the churn table. For High Needs data use the '… | HN | …' columns.",
    "Medicare Enrollment Type": "Header cell of the PY risk table (text 'BY3 CMS-HCC Risk Score [A]').",
    "Medicare Enrollment Type / BY3 CMS-HCC Risk Score\n[A]": "Header cell of the PY risk table (text 'CMS-HCC Risk Ratio (Uncapped) [C]').",
    "Exp PMPM [Trend Calculations!B4]": "Year header (2023) of the trend-calculations expense table.",
    "Exp PMPM [Trend Calculations!C4]": "Year header (2024) of the trend-calculations expense table.",
    "Exp PMPM [Trend Calculations!D4]": "Year header (2025) of the trend-calculations expense table.",
    "Exp PMPM / Actuals [Trend Calculations!G4]": "Year header (2026) of the trend-calculations expense table.",
    "Exp PMPM / Actuals [Trend Calculations!H4]": "Year header (2027) of the trend-calculations expense table.",
    "Risk Score [2025-2026] [Trend Calculations!B39]": "Year header (2023) of the trend-calculations risk table.",
    "Risk Score [2026-2027]": "Despite the name, a year header cell (2024) of the trend-calculations risk table.",
    "Risk Score [2025]": "Year header cell (2025) of the trend-calculations risk table.",
    "Risk Score [Aged & Disabled (A&D)]": "Despite the name, a year header cell (2026) of the trend-calculations risk table. For A&D risk use 'Renormalized average risk | AD | …' or 'Capped PY risk score | AD | PY2027'.",
    "Risk Score [2025-2026] [Trend Calculations!F39]": "Year header (2027) of the trend-calculations risk table.",
    "Beneficiary Counts [2025-2026]": "Year header cell (2023) of the beneficiary-count table.",
    "Beneficiary Counts [2026-2027]": "Year header cell (2024) of the beneficiary-count table.",
    "Beneficiary Counts [2025]": "Year header cell (2025) of the beneficiary-count table.",
    "Beneficiary Counts [Aged & Disabled (A&D)]": "Despite the name, a year header cell (2026) of the beneficiary-count table. For A&D counts use 'Beneficiaries | AD | <year>'.",
    "Exp PMPM [2023]": "Year header (2023).", "Exp PMPM [2024]": "Year header (2024).",
    "Exp PMPM [2025]": "Year header (2025).", "Exp PMPM [2026]": "Year header (2026).",
    "Risk [2023]": "Year header (2023).", "Risk [2024]": "Year header (2024).",
    "Risk [2025]": "Year header (2025).", "Risk [2026]": "Year header (2026).",
    "Trend_Calculations__A94": "Year header (2025).", "Trend_Calculations__A95": "Year header (2026).",
    "Trend_Calculations__A96": "Year header (2027).", "Trend_Calculations__G75": "Constant 1 (placeholder cell).",
    "Assignable__A3": "Row caption 'National' of the Assignable sheet.",
    "Assignable__AH1": "Template note text; not data.", "Assignable__AL1": "Template note text; not data.",
    "Assignable__AP1": "Template note text; not data.",
    "Assignable__AG1": "Blank template denominator (0); not data.", "Assignable__AK1": "Blank template denominator (0); not data.",
    "Assignable__AO1": "Blank template denominator (0); not data.",
}
for c, d in LABELS.items():
    add(c, "label", d)
for col, yr in zip(["BB1", "BC1", "BD1", "BE1", "BF1", "BG1", "BH1", "BI1", "BJ1", "BK1", "BL1", "BM1"],
                   [2023, 2024, 2025, 2026] * 3):
    add(f"Assignable__{col}", "label", f"Year header ({yr}) of the regional risk-standardized expenditure block.")
for cell in ["B15", "F15", "B23", "B30", "B48", "F48", "B56", "B63"]:
    add(f"Selected alignment type (display) [Configuration display] [Trend Calculations!{cell}]", "duplicate",
        "Display echo of 'Alignment type' (PROSPECTIVE).")
for cell in ["A30", "A63"]:
    add(f"Selected trend option (display) [Configuration display] [Trend Calculations!{cell}]", "duplicate",
        "Display echo of 'Expense and risk trend option' (Historic).")

# ---------------------------------------------------------------- PROSP sheet row 3 (TIN inputs)
add("PROSP__A3", "label", "Blank.")
add("PROSP__B3", "raw", "Blank in this extract.")
add("PROSP__C3", "raw", "Blank in this extract.")
add("PROSP__D3", "duplicate", "Same as 'Total cohort beneficiaries | 2024'.")
add("PROSP__E3", "duplicate", "Same as 'Total cohort beneficiaries | 2025'.")
add("PROSP__F3", "duplicate", "Same as 'Total cohort beneficiaries | 2026' (= 'BY3 aligned beneficiaries (2026 eligibility count)').")
add("PROSP__G3", "duplicate", "Same as '2027 aligned beneficiaries'.")
layout = [  # (cells, family, cohort)
    (["I3", "J3", "K3"], "Treated beneficiaries", "AD"), (["M3", "N3", "O3"], "Treated beneficiaries", "HN"),
    (["Q3", "R3", "S3"], "Treated beneficiaries", "ESRD"),
    (["U3", "V3", "W3"], "Treated member months", "AD"), (["Y3", "Z3", "AA3"], "Treated member months", "HN"),
    (["AC3", "AD3", "AE3"], "Treated member months", "ESRD"),
    (["AS3", "AT3", "AU3"], "Raw risk", "AD"), (["AW3", "AX3", "AY3"], "Raw risk", "HN"),
    (["BA3", "BB3", "BC3"], "Raw risk", "ESRD"),
]
for cells, fam, coh in layout:
    for cell, yr in zip(cells, [2024, 2025, 2026]):
        add(f"PROSP__{cell}", "duplicate", f"Same as '{fam} [{yr} {coh}]'.")
for cells, coh in [(["AG3", "AH3", "AI3"], "AD"), (["AK3", "AL3", "AM3"], "HN"), (["AO3", "AP3", "AQ3"], "ESRD")]:
    for cell, yr in zip(cells, [2024, 2025, 2026]):
        add(f"PROSP__{cell}", "raw", f"Source paid PMPM for {coh} {yr} from the PROSP input sheet (the 2026 value equals 'Reach PMPM [2026 {coh}]'; 2024–2025 differ slightly from the Reach PMPM columns). Prefer the named 'Reach PMPM' / 'Net cost PMPM' columns.")
for cell in ["H3", "L3", "P3", "T3", "X3", "AB3", "AF3", "AJ3", "AN3", "AR3", "AV3", "AZ3"]:
    add(f"PROSP__{cell}", "label", "Blank spacer column of the PROSP input sheet.")

# ---------------------------------------------------------------- PROSP_COUNTY row 3
add("PROSP_COUNTY__A3", "label", "Blank."); add("PROSP_COUNTY__B3", "label", "Blank."); add("PROSP_COUNTY__C3", "label", "Blank.")
add("PROSP_COUNTY__D3", "raw", "County-assigned beneficiaries, A&D cohort, 2026 (county-matched population used for regional weights). D3+E3+F3 = G3.")
add("PROSP_COUNTY__E3", "raw", "County-assigned beneficiaries, High Needs cohort, 2026. D3+E3+F3 = G3.")
add("PROSP_COUNTY__F3", "raw", "County-assigned beneficiaries, ESRD cohort, 2026 (= Assignable__BP4). D3+E3+F3 = G3.")
add("PROSP_COUNTY__G3", "raw", "County-assigned beneficiaries, all cohorts, 2026 (sum of D3..F3). Close to but not identical with 'Total cohort beneficiaries | 2026'.")
add("PROSP_COUNTY__H3", "label", "Blank."); add("PROSP_COUNTY__I3", "label", "Blank.")

# ---------------------------------------------------------------- Assignable sheet
# row 3: national reference values; row 4: national assignable totals; row 2: regional PBPM
for cells, coh in [(["AP3", "AQ3", "AR3", "AS3"], "AD"), (["AT3", "AU3", "AV3", "AW3"], "HN"), (["AX3", "AY3", "AZ3", "BA3"], "ESRD")]:
    for cell, yr in zip(cells, [2023, 2024, 2025, 2026]):
        add(f"National [LEAD Assignable!{cell}]", "duplicate" if yr > 2023 else "raw",
            f"National average risk score, {coh} cohort, {yr}" + (" (same as 'National risk score | %s | %d')." % (coh, yr) if yr > 2023 and not (coh == "HN" and yr == 2026) else (" (2023 not available: 0)." if yr == 2023 else ". Only source for HN 2026.")))
for cells, coh in [(["BB3", "BC3", "BD3", "BE3"], "AD"), (["BF3", "BG3", "BH3", "BI3"], "HN"), (["BJ3", "BK3", "BL3", "BM3"], "ESRD")]:
    for cell, yr in zip(cells, [2023, 2024, 2025, 2026]):
        add(f"National [{yr}] [LEAD Assignable!{cell}]", "duplicate" if yr > 2023 else "raw",
            f"National assignable expenditure PBPM, {coh} cohort, {yr}" + (f" (same as 'National expenditure PBPM | {coh} | {yr}')." if yr > 2023 else " (2023 not available: 0)."))
groups4 = [("B4 C4 D4 E4", "national assignable beneficiaries, all cohorts"), ("F4 G4 H4 I4", "national assignable beneficiaries, A&D"),
           ("J4 K4 L4 M4", "national assignable beneficiaries, High Needs"), ("N4 O4 P4 Q4", "national assignable beneficiaries, ESRD"),
           ("R4 S4 T4 U4", "national assignable member months, A&D"), ("V4 W4 X4 Y4", "national assignable member months, High Needs"),
           ("Z4 AA4 AB4 AC4", "national assignable member months, ESRD"), ("AD4 AE4 AF4 AG4", "national assignable paid dollars, A&D"),
           ("AH4 AI4 AJ4 AK4", "national assignable paid dollars, High Needs"), ("AL4 AM4 AN4 AO4", "national assignable paid dollars, ESRD"),
           ("AP4 AQ4 AR4 AS4", "national risk numerator (risk × member months), A&D"), ("AT4 AU4 AV4 AW4", "national risk numerator, High Needs"),
           ("AX4 AY4 AZ4 BA4", "national risk numerator, ESRD")]
for cells, what in groups4:
    for cell, yr in zip(cells.split(), [2023, 2024, 2025, 2026]):
        add(f"Assignable__{cell}", "raw", f"National reference total: {what}, {yr}" + (" (2026 = Jan–May)" if yr == 2026 else "") + (" — not available, 0." if yr == 2023 else ". Inferred from values (A&D + HN + ESRD = total); same in every row."))
for cell, coh in [("BN4", "A&D"), ("BO4", "High Needs"), ("BP4", "ESRD")]:
    add(f"Assignable__{cell}", "raw", f"County-assigned beneficiaries 2026, {coh} cohort (same values as PROSP_COUNTY row 3).")
for cell, coh in [("BQ4", "AD"), ("BR4", "HN"), ("BS4", "ESRD")]:
    add(f"Assignable__{cell}", "duplicate", f"Same as 'National blend weight | {coh} | <year>' (the TIN's share of its regional assignable population; identical for all years).")
for cells, coh in [(["BB2", "BC2", "BD2", "BE2"], "AD"), (["BF2", "BG2", "BH2", "BI2"], "HN"), (["BJ2", "BK2", "BL2", "BM2"], "ESRD")]:
    for cell, yr in zip(cells, [2023, 2024, 2025, 2026]):
        add(f"Assignable__{cell}", "duplicate" if yr > 2023 else "raw",
            f"Regional risk-standardized expenditure PBPM, {coh}, {yr}" + (f" (same as 'Regional risk-standardized expenditure PBPM | {coh} | {yr}')." if yr > 2023 else " (2023 not available: 0)."))

# ---------------------------------------------------------------- PQEM sheet (REACH capitation reference data, constants)
pq = {"B3 C3 D3": "beneficiaries 2025", "E3 F3 G3": "beneficiaries 2026 (Jan–May)", "H3 I3 J3": "member months 2025",
      "K3 L3 M3": "member months 2026 (Jan–May)", "N3 O3 P3": "REACH total paid $ 2025 (sum = 'Fixed workbook PQEM | REACH total paid | 2025')",
      "Q3 R3 S3": "REACH total paid $ 2026 Jan–May (sum × 2.4 × 1.0612 = the 2026 annualized total)",
      "T3 U3 V3": "PCC paid PQEM $ 2025 (sum = 'Fixed workbook PQEM | PCC paid PQEM | 2025')", "W3 X3 Y3": "PCC paid PQEM $ 2026 Jan–May",
      "Z3 AA3 AB3": "paid $ 2025, category not documented", "AC3 AD3 AE3": "paid $ 2026 Jan–May, category not documented",
      "AF3 AG3 AH3": "TCC paid $ 2025 (sum = 'Fixed workbook PQEM | TCC paid | 2025')", "AI3 AJ3 AK3": "TCC paid $ 2026 Jan–May",
      "AL3 AM3 AN3": "paid $ 2025, category not documented", "AO3 AP3 AQ3": "paid $ 2026 Jan–May, category not documented"}
for cells, what in pq.items():
    for cell, coh in zip(cells.split(), ["A&D", "ESRD", "High Needs"]):
        add(f"PQEM__{cell}", "raw", f"REACH primary-care capitation reference data (national constant, same in every row): {what}, {coh} cohort. Cohort order inferred from values. Prefer the named 'Fixed workbook PQEM | …' columns.")
for cell in ["T1", "U1", "V1"]:
    add(f"PQEM__{cell}", "raw", "Ratio from the PQEM reference sheet (constant); meaning not documented in the extract. Prefer 'Fixed workbook PQEM | Base PCC fraction | …'.")

# ---------------------------------------------------------------- named columns that mislead
NAMED = {
    "Benchmark discount": ("parameter", "The discount RATE applied to this TIN's benchmark (0.03 for Low Spending, 0.0175 for High Spending), not a dollar or PBPM amount. 'Benchmark PBPM after discount' = 'Benchmark PBPM before discount' × (1 − this rate)."),
    "Administrative add-on": ("metric", "Total DOLLARS (not PBPM): 1.5% × 'Benchmark PBPM before discount' × person years × 12 for High Spending TINs; 0 for Low Spending. Paid separately from the benchmark."),
    "Settlement | total monies owed": ("metric", "Net settlement in dollars: shared savings/losses + sequestration + enhanced PCC repayment (+ APO and high-performers items, both 0 here). POSITIVE = CMS pays the ACO; NEGATIVE = the ACO owes CMS (often because the enhanced PCC advance exceeds shared savings)."),
    "Settlement | enhanced PCC repayment": ("metric", "Negative dollars: repayment of the Enhanced PCC advance at settlement (≈ −Σ 'Enhanced PCC amount | cohort')."),
    "Settlement | sequestration": ("metric", "Negative dollars: 2% of the absolute shared savings/losses amount."),
    "Settlement | shared savings or losses": ("metric", "Shared savings (+) or losses (−) in dollars after the Global risk corridors. Identical to 'Retained savings or losses after risk corridors'."),
    "Retained savings or losses after risk corridors": ("duplicate", "Same as 'Settlement | shared savings or losses'."),
    "Gross margin / total savings before risk corridors": ("metric", "Total dollars: 'Total benchmark' − 'Total projected expenditures'. Positive = savings, negative = losses. This is the headline pre-sharing result."),
    "Total benchmark": ("metric", "Total dollars = 'Benchmark PBPM after discount and earned quality' × 'Person years after exposure adjustment' × 12."),
    "Total projected expenditures": ("metric", "Total dollars = 'Projected expense PBPM' × 'Person years after exposure adjustment' × 12."),
    "Spending classification": ("duplicate", "Same as 'ACO spending classification'."),
    "Quality score [Expense, benchmark and margin]": ("duplicate", "Same as 'Quality score [Model settings]' (1 = full quality withhold earned back)."),
    "Financial guarantee | guarantee fraction": ("duplicate", "Same as 'Financial guarantee fraction' (0.04)."),
    "Financial guarantee | annualized BY3 cost": ("metric", "Σ over cohorts of 'Claim payments | cohort | BY3 2026' × 2.4 (Jan–May 2026 paid annualized). The guarantee is 4% of this."),
    "Financial guarantee amount": ("metric", "Dollars = 4% × 'Financial guarantee | annualized BY3 cost'."),
    "Claim payments | AD | BY1 2024": ("metric", "Dollars (not annualized) = 'Expenditure PBPM | AD | BY1 2024' × 'Eligible member months | AD | BY1 2024'. Same construction for every cohort and base year; BY3 2026 covers Jan–May only."),
    "Benchmark PBPM before discount": ("metric", "Σ over cohorts of 'Cohort share | cohort | PY2027' × 'Updated benchmark PBPM | cohort | PY2027'. Identical to 'Total updated benchmark PBPM before discount and quality'."),
    "Total updated benchmark PBPM before discount and quality": ("duplicate", "Same as 'Benchmark PBPM before discount'."),
    "Benchmark PBPM after discount and earned quality": ("metric", "The final PY2027 benchmark PBPM used for savings. Equals 'Benchmark PBPM after discount' here because the quality score is 1 (the whole 3% withhold is earned back)."),
    "Quality withhold PBPM": ("metric", "3% × 'Benchmark PBPM after discount'. Equals 'Earned quality withhold PBPM' because the quality score is 1."),
    "Earned quality withhold PBPM": ("duplicate", "Same as 'Quality withhold PBPM' (quality score = 1)."),
    "Benchmark PBPM after discount": ("duplicate", "Same as 'Benchmark PBPM after discount and earned quality' in this file (quality score = 1)."),
    "Pre-sharing MLR = expense / benchmark": ("metric", "'Projected expense PBPM' ÷ 'Benchmark PBPM after discount and earned quality' (= expense $ ÷ benchmark $). Medical-loss-ratio style figure; below 1 means savings."),
    "Post-sharing MLR = 1 − retained savings / benchmark": ("metric", "1 − 'Settlement | shared savings or losses' ÷ 'Total benchmark'."),
    "Assigned beneficiaries": ("metric", "PY2027 aligned beneficiaries used for person years (= '2027 aligned beneficiaries' where supplied). 'Person years after exposure adjustment' = this × 'Exposure retention factor … | Average'."),
    "2027 aligned beneficiaries": ("metric", "Supplied PY2027 alignment count (blank for 223 TINs where the model projected it instead; see '2027 beneficiary projection basis')."),
    "BY3 aligned beneficiaries (2026 eligibility count)": ("duplicate", "Same as 'Total cohort beneficiaries | 2026'."),
    "Total cohort beneficiaries | 2026": ("metric", "2026 (BY3) beneficiaries across AD + HN + ESRD; the '200plus' file filter applies to this count."),
    "Person years after exposure adjustment": ("metric", "PY2027 person years = 'Assigned beneficiaries' × 'Exposure retention factor (workbook label: Churn Rate) | Average'. The denominator for all PBPM → dollar conversions (× 12)."),
    "Exposure retention factor (workbook label: Churn Rate) | Average": ("metric", "Share of the year an aligned beneficiary stays exposed (0.66–1.0, median 0.97). The workbook calls it 'Churn Rate' but it is a RETENTION factor, higher = less churn."),
    "Cohort share | AD | PY2027": ("metric", "'Person years by cohort | AD | PY2027' ÷ 'Person years after exposure adjustment' (same construction for HN and ESRD). Near-identical to 'Cohort allocation weight' and 'Cohort allocation share'."),
    "Beneficiary category weight | AD | BY3 2026": ("metric", "'Beneficiaries | AD | 2026' ÷ 'Total cohort beneficiaries | 2026' (2026 mix, used to weight the BY3 benchmark); the PY2027 mix is 'Cohort share | AD | PY2027'."),
    "Regional adjustment weight": ("parameter", "0.5 for Low Spending TINs (regional adjustment applies), 0 for High Spending TINs."),
    "Selected ACO-specific adjustment type": ("metric", "'Regional' for Low Spending TINs, 'Prior Savings' for High Spending TINs (whose prior-savings adjustment is 0 because no TIN is eligible)."),
    "ACO-specific benchmark adjustment | AD | Adjustment": ("duplicate", "Same as 'Regional adjustment after cap | AD | BY3' (also for HN and ESRD)."),
    "Adjusted historical benchmark PBPM | AD | Adjusted": ("duplicate", "Same as 'Adjusted historical benchmark PBPM | AD | BY3' (also for HN and ESRD)."),
    "Net cost PMPM [2024 AD]": ("metric", "'Reach PMPM' − 'SAHS PMPM' − 0.65 × 'Skin PMPM' for the same year/cohort (SAHS 100% excluded, skin substitutes 65% excluded). Same construction for every year and cohort."),
    "Reach PMPM [2024 AD]": ("metric", "Source paid PMPM from the REACH claims extract for the year/cohort, before SAHS and skin-substitute exclusions."),
    "Treated Reach PMPM [2024 AD]": ("metric", "Reach PMPM after the blank / −11 member-month and blank-dollar treatments; in 2026 equals 'Net cost PMPM'."),
    "Blank member months": ("parameter", "Imputation rule: source member months that are blank are replaced with 3."),
    "Member months = -11": ("parameter", "Imputation rule: source member months coded −11 (CMS small-cell suppression) are replaced with 8."),
    "Blank dollars": ("parameter", "Imputation rule: blank source dollar amounts are treated as 0."),
    "Full-year denominator": ("parameter", "12 months — divisor used to convert annual amounts to PBPM."),
    "2026 exposure months": ("parameter", "5 — months of 2026 claims available (Jan–May)."),
    "BY3 annualization factor (12/5)": ("parameter", "2.4 — multiplies Jan–May 2026 amounts to a full year."),
    "Skin exclusion factor": ("parameter", "0.65 — share of skin-substitute spending excluded from benchmark and expense."),
    "Minimum beneficiary equivalent threshold for base-year inclusion": ("parameter", "A base year is used only if the TIN had at least 10 beneficiaries in it (see 'Base year eligible | BYn' and 'Number of eligible base years')."),
    "Input notes": ("metric", "Source caveats per TIN, e.g. 'Organization-level NPI data also map to selection keys …: do not add these rows as independent populations' — the TINs listed share one NPI population."),
    "National expense trend | ESRD | Average / 2026–2027": ("duplicate", "Same as 'National expense trend | ESRD | 2026–2027' (label artifact). Likewise for HN and AD."),
    "Regional expense trend | AD | Average / 2026–2027": ("duplicate", "Same as 'Regional trend factor | AD | 2027' (label artifact)."),
    "Applied risk trend | ESRD | 2025–2026": ("parameter", "'-' = not applicable under prospective alignment (risk trend is applied only to HN: 1.04)."),
    "Cumulative corridor dollar threshold | Corridor 1": ("metric", "Dollar edge of each Global corridor band: 15% / 35% / 50% / 100% of 'Total benchmark'."),
    "Gross savings or losses in corridor | Corridor 1": ("metric", "Portion of the gross margin falling in each corridor band (dollars, signed). 'Retained … in corridor' = this × the band's sharing fraction (100% / 50% / 25% / 10%)."),
    "Cohort revenue before discount | AD": ("metric", "Dollars = 'Updated benchmark PBPM | AD | PY2027' × 'Person years by cohort | AD | PY2027' × 12; base for the PCC amounts (same for HN, ESRD)."),
    "PCC capitation amount | AD": ("metric", "Dollars = Base PCC fraction (3.164%) × 'Cohort revenue before discount | AD'."),
    "Enhanced PCC amount | AD": ("metric", "Dollars = Enhanced PCC fraction (3.836%) × 'Cohort revenue before discount | AD'; repaid at settlement."),
    "BY3 national expenditure PBPM weighted by beneficiary categories and capped risk": ("metric", "National reference PBPM for the TIN's 2026 cohort mix and capped risk; used for the regional/discount caps."),
    "Weighted regional-minus-ACO difference": ("metric", "PBPM dollars: regional risk-standardized expenditure minus the TIN's historical benchmark, weighted across cohorts (positive = TIN is cheaper than its region → Low Spending)."),
    "Relative regional-minus-ACO difference": ("metric", "'Weighted regional-minus-ACO difference' as a fraction of the regional PBPM."),
}
for c, (k, d) in NAMED.items():
    add(c, k, d)
# patterns for trailing-pipe names
add(r"^BY3 renormalized risk \| (AD|HN|ESRD) \|$", "duplicate", "Same as 'Renormalized average risk | <cohort> | BY3 2026' (the empty last segment is a label artifact).")
add(r"^Final capped PY risk score \| (AD|HN|ESRD) \|$", "duplicate", "Same as 'Capped PY risk score | <cohort> | PY2027'.")
add(r"^Displayed risk growth cap \| (AD|HN|ESRD) \|$", "parameter", "The risk-growth cap shown for the cohort (1.03 for AD/ESRD, 1.04 for HN).")
add(r"^Uncapped (PY/BY3 risk ratio|projected PY renormalized risk) \| (AD|HN|ESRD) \|$", "metric", "PY2027 risk relative to BY3 before the 3%/4% cap (the empty last segment is a label artifact).")
add(r"^Churn calculation \| beneficiaries \| (AD|HN|ESRD|Total) \| 20\d\d$", "duplicate", "Same as 'Beneficiaries | <cohort> | <year>' / 'Total cohort beneficiaries | <year>'.")
add(r"^Churn calculation \| member months \| (AD|HN|ESRD) \| 20\d\d$", "duplicate", "Same as 'Eligible member months | <cohort> | BYn <year>'.")
add(r"^Expenditure PBPM \| (AD|HN|ESRD) \| BY[12] 20\d\d$", "duplicate", "Same as 'Assigned expenditure PBPM | <cohort> | <year>'; BY3 2026 equals 'Assigned expenditure PBPM | <cohort> | 2026 blended'.")
add(r"^Benchmark update trend \| (AD|HN|ESRD) \| Applied PY trend$", "duplicate", "Same as 'Benchmark update trend | <cohort> | Three-way blended trend after guardrail' — the factor actually applied to reach PY2027.")
add(r"^Benchmark update trend \| (AD|HN|ESRD) \| Two-way blended trend$", "duplicate", "Same as 'National-regional blended trend factor | <cohort> | 2027'.")
add(r"^(National|Regional) blend weight \| (AD|HN|ESRD) \| 20\d\d$", "metric", "Weight on the national (resp. regional) trend = the TIN's share of its regional assignable population (tiny for a single TIN) — identical for every year.")
add(r"^(Assigned expenditure PBPM|Risk renormalization factor|Assigned raw risk score|Beneficiaries|National (expenditure PBPM|risk score)) \| (AD|HN|ESRD) \| 2023$", "label", "2023 is not a base year: placeholder 0.")
add(r"^Beneficiary status \[20\d\d (AD|HN|ESRD)\]$", "metric", "Source-data status for the year/cohort: Observed, 'Imputed from treated member months', or 'No source record' (use to exclude imputed TINs).")

with OUT.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["column", "kind", "definition"])
    w.writerows(rows)
print(f"wrote {len(rows)} notes to {OUT}")
