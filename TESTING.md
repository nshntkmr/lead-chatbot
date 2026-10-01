# Test script — ACO Data Assistant

Every expected value below was computed directly from the two CSV files (LEAD 11,865 TINs, MSSP 9,419 TINs), not by the chatbot. If an answer differs by more than rounding, copy the question and the app's answer and we'll trace it.

**Before you start**

1. `.env` has `ANTHROPIC_API_KEY`; run `start.bat`; sign in at http://localhost:8000.
2. The home screen must show the two dataset cards (LEAD / MSSP). If it shows only one, the MSSP CSV isn't in `data\`.
3. For each test: note whether the figures match, whether the right card/table/chart appeared, and anything the answer got wrong or waffled on.

Conventions: MLR = expense ÷ benchmark. "Margin" = benchmark − expense (savings positive). Dollar figures ±0.5%, percentages ±0.1 pt are fine.

---

## Part A — LEAD dataset (start a new chat, pick LEAD)

| # | Ask | Expected |
|---|---|---|
| A1 | How many TINs are in the data, what's the median MLR, and how many are at or under 85%? | **11,846** TINs with a benchmark (19 have zero benchmark; 11,865 rows total), median MLR **95.8%**, **834** at or under 85%. |
| A2 | Compare High vs Low Spending TINs: count, total benchmark, total margin, combined MLR. Show a chart. | Low Spending: **7,422** TINs, benchmark **$209.8B**, margin **$12.3B**, MLR **94.1%**. High Spending: **4,443**, **$91.1B**, **$2.1B**, MLR **97.7%**. A bar chart should render. |
| A3 | Which 5 TINs have the largest projected savings before risk corridors? | UC Regents 954373071 **$160.9M** (MLR 87.4%), Sutter Bay 941156581 **$110.7M**, DuPage Medical Group 362657618 **$102.8M**, Allina 363261413 **$85.8M**, IHC Health Services 942854057 **$81.8M**. |
| A4 | I have TINs 10198331, 10211494, 10211501, 10211534 and 10211551. What is my combined MLR and projected savings? My target is 85%. | Combined MLR **97.3%**; benchmark **$174.6M**, expense **$169.8M**, margin **$4.77M**, **10,044** person-years; net shared savings after corridors and sequestration **$4.67M**; enhanced PCC repayment **−$6.90M**; total monies owed **−$2.23M** (ACO owes CMS); financial guarantee **$6.32M**. Misses 85% by **$21.4M** of expense (12.6%). Cohorts on the same discounted basis: A&D **91.6%** / +$6.72M, High Needs **101.7%** / −$1.47M, ESRD **106.6%** / −$0.48M (they must sum to the $4.77M). The −$58.9M figure is a *scenario* (loss = 100% of benchmark), not a cap; the answer should not call it the worst case. A portfolio table with a TOTAL row and the header chip "Portfolio: 5 TINs · target MLR 85%" should appear. Must say the combined MLR is expense ÷ benchmark, not an average. |
| A5 | Which TINs could I add to bring that portfolio to 85%? | None of the five is individually under 85%, so removal can't get there. Fewest additions: **910214500 Optum Care Washington** (MLR 75.8%) → combined 86.2%, then **271081647 UNC Physicians Network** (80.6%) → **83.6%**. 834 TINs are candidates at or under 85%. |
| A6 | Add those two to my portfolio. What's my MLR now? | **83.6%**, margin **$111.1M**, 7 TINs. Chip updates to "Portfolio: 7 TINs". |
| A7 | Go back to the original five. If projected expense runs 3% hot, what happens? | Must NOT change the saved portfolio (what-if). MLR **100.2%**, margin **−$329k**, net shared result **−$336k**. (Set the portfolio back to the five first if it added them permanently — that's acceptable if it asks.) |
| A8 | Which TINs with at least 1,000 beneficiaries have the highest home-health utilization prevalence, and what are their MLRs? | The answer must say which beneficiary count it filtered on, and either basis is acceptable. **PY2027 `Assigned beneficiaries` (preferred):** MVP Medical Group 992506226 **97.8%** / MLR 97.5%; Legacy Marketing Worldwide 474496596 97.2% / 96.2%; A&E Medical Group 862688458 97.1% / 89.0%; 2,520 TINs pass, 2,466 have prevalence (54 missing), median 6.9%; exactly **two** of the top 15 are ≤ 90% (Mobile Care 88.0%, A&E 89.0% — Wound Management is 90.14%). **2026 `Total cohort beneficiaries \| 2026`:** Perpetual Mobile Medical Group 881934998 97.8% / 94.3%; Home Care MD 844806153 97.4% / 89.8%; California Mobile 934400923 97.4% / 95.4%. Must not call ~98% prevalence a likely data error (these are house-call practices), and must not compare the top 15 with "all eligible" as if that were "the rest". |
| A9 | What share of total person-years is High Needs, and what share is ESRD? | HN **18.7%**, ESRD **0.8%**. |
| A10 | What is the quality withhold, the benchmark discount for high- and low-spending ACOs, and the first Global corridor threshold? | **3%**; **1.75%** high / **3%** low; **15%** of benchmark. Should answer from the constants without a long query. |
| A11 | What does the column "ESRD" contain? | Must say it's a worksheet label cell holding 2024 in every row, not ESRD data, and point to the `… \| ESRD \| …` columns. |
| A12 | What is "Benchmark discount" — a dollar amount? | Must say it's the **rate** (0.03 / 0.0175), and that `Benchmark PBPM after discount` = before × (1 − rate). |
| A13 | Show every TIN whose name contains "Regents of the University of California" with benchmark, MLR and shared savings. | A table of **10** TINs. Largest 954373071 ($1.27B, 87.4%, $160.9M shared); also 680344702 ($446.8M, 99.3%, High Spending). |
| A14 | Build me a recruiting list: the 20 largest Low-Spending TINs by benchmark with MLR under 90%, excluding my portfolio. | First three: UC Regents 954373071 **$1,271.3M** / 87.35%; Allina **$788.3M** / 89.12%; DuPage **$756.1M** / 86.40%. 20th: Alegent Creighton Clinic **$315.4M** / 88.49%. UNC Physicians (in the portfolio if A6 was kept) must be excluded. |

## Part B — MSSP dataset (new chat, pick MSSP)

| # | Ask | Expected |
|---|---|---|
| B1 | How many TINs, median MLR, how many under 85%, and how many fall in the no-shared-savings band? | **9,419**; median MLR **95.2%**; **791** at or under 85%; **435** "No Shared Savings" (inside the ±0.5% MSR/MLR band). |
| B2 | Break the TINs down by savings/losses status with total benchmark and net shared result. Chart it. | Saving **6,982** TINs / $156.7B benchmark / **+$7,719M** net shared; Losses **2,002** / $36.9B / **−$551M**; No Shared Savings **435** / $18.0B / $0. |
| B3 | How many TINs exceed the 20% shared-savings cap, and by how much in total? | **53** TINs, **$23.7M** overstated in the workbook's uncapped figures. Must mention the workbook doesn't apply the cap. |
| B4 | I have TINs 941156581, 363738206 and 340714585. Combined MLR and shared savings under ENHANCED? Target 90%. | MLR **98.2%**; benchmark **$3.69B**, expense **$3.63B**, margin **$67.8M**, **231,282** person-years; status Saving; shared savings **$50.9M** (75% rate; cap not binding); financial guarantee **$16.0M**. Cohort MLRs: ESRD 98.6%, Disabled 98.5%, Aged/dual **95.0%**, Aged/non-dual 98.4%. |
| B5 | Compare LEAD and MSSP for this portfolio. | LEAD: benchmark **$4.40B**, margin **$170.9M**, MLR **96.1%**, shared **$167.5M**. MSSP: **$3.69B**, **$67.8M**, **98.2%**, **$50.9M**. A two-column comparison table. Should note the two workbooks model different populations/rules. |
| B6 | How many TINs qualify for the Health Equity Benchmark Adjustment, and what's the average adjustment per beneficiary for those that do? | **1,837** TINs; **$261.72** per beneficiary. |
| B7 | Top 5 TINs by net shared result. | Sutter Bay 941156581 **$70.4M**; DuPage 362657618 **$64.6M**; then three UC Regents TINs (954373071, 954415773, 721524529) each **$62.9M** — the answer should notice these three are identical / share an NPI. |
| B8 | What's my combined savings if my portfolio is 954373071, 954415773 and 721524529? | Benchmark $3.00B, MLR 91.6% — but the **shared-NPI warning must appear**: all three map to NPI 1235107566, so the figures triple-count one population. This is the key trap test. |
| B9 | What are the MSR, the final sharing rate and the shared loss rate in this workbook? | MSR **0.5%**, sharing rate **75%**, loss rate **40%**, track ENHANCED. |
| B10 | What does "Minimum Loss Rate" mean here — is that the MLR you've been reporting? | Must distinguish: Minimum Loss Rate = the −0.5% threshold; the MLR reported = expense ÷ benchmark. |
| B11 | How is the regional adjustment weighted? | **35%** when the TIN is below its region (5,382 TINs), **15%** when above (4,037). |
| B12 | For Sutter Bay (941156581), compare MSSP and LEAD. | MSSP benchmark **$1,535.3M**, MLR 93.9%, net shared **$70.4M**; LEAD benchmark **$1,731.5M**, MLR 93.6%, shared **$110.7M**. |

## Part C — behaviour, not numbers

| # | Check | Pass if |
|---|---|---|
| C1 | Refresh the page mid-way through Part A. | The chat reloads with the portfolio chip and dataset tag intact. |
| C2 | Open a LEAD chat and ask an MSSP-only question ("how many TINs are in the no-shared-savings band?"). | It says that's in the MSSP dataset and suggests a new MSSP chat (or uses compare_programs where relevant) rather than inventing a number. |
| C3 | Ask "Which TINs are in Texas?" | Says there is no state/county data and offers a name filter. |
| C4 | Ask "What if the discount were 2% instead of 3%?" | Explains it can't re-run the model, offers the expense/benchmark stress test instead. |
| C5 | Expand a "Ran a query" line under an answer. | The SQL is visible; column names are quoted correctly. |
| C6 | Click Download CSV on a table and Download PNG on a chart. | Files download with sensible names. |
| C7 | Second browser / second user (create with `manage_users add`). | Sees only their own chats. |
| C8 | Sign out, sign in with a wrong password 8 times. | Locked out for 15 minutes with a clear message. |
| C9 | After any answer, look under it. | A grey line like `≈ 76,000 tokens · $0.04 · 3 model calls`. The sidebar footer shows "$x this month · $y all time" and increases after each answer. |
| C10 | Click your name in the sidebar. | The Usage and spend panel: this chat / today / month / all time, token breakdown, by model, recent chats, rates. Sign out and back in — the totals are still there. An admin sees an "All users" table; a non-admin does not. |
| C11 | Sanity-check one cost. | With Opus 5.5 at list price, a call with 1,200 uncached input, 24,000 cached-read and 60 output tokens costs 1,200×$4 + 24,000×$0.20 + 60×$20 = $10,800 per million = **$0.0108**. The first question of a new chat has a cache *write* (~25k tokens at $5/M ≈ $0.13) and later ones mostly cache *reads*. |

## What to send back

For any failure: the dataset, the exact question, the app's answer (paste), and the expected value from this sheet. Screenshots help for layout issues.
