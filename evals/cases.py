"""Eval cases: TESTING.md as data. Expected values were computed from the raw CSVs, not by the chatbot.

A case is one chat: a program and one or more turns. Each turn has checks on the answer the user would see
(the reply text plus every table / chart / tool line shown under it).

Numeric facts carry a value WITH ITS SIGN and a plain-language statement of what the number is (metric,
entity, basis). They are graded twice (see run.py): a deterministic pass (is the figure shown at all, and is
it shown with the right sign where the sign is explicit), then a model judge that reads the answer and
decides whether that figure is stated for that metric — so a right number attached to the wrong metric, a
flipped sign in prose, or prose that contradicts its own table does not pass.

  usd(v, what)      a dollar figure, ±0.5 % unless rel= is given. Negative v = owed / loss / shortfall.
  pct(v, what)      a percentage as displayed (97.3 means 97.3 %), ±0.1 point unless tol= is given
  count(v, what)    an exact count (rel= for a tolerance)
  has(regex)        the text must match        lacks(regex)   the text must not match
  shows(kind)       a block of that type ("table", "chart") was shown
  portfolio(n)      the saved working portfolio has n TINs (several sizes may be allowed)
  target(v)         the saved target MLR
  chart_scale()     every chart labelled as a percentage holds percentage values (87.35), not fractions (0.8735)
"""
from __future__ import annotations

from dataclasses import dataclass, field


def usd(v: float, what: str, rel: float = 0.005) -> dict:
    sign = "−" if v < 0 else ""
    return {"kind": "num", "value": v, "tol": abs(v) * rel, "unit": "usd", "what": what,
            "label": f"{what}: {sign}${abs(v):,.0f}"}


def pct(v: float, what: str, tol: float = 0.1) -> dict:
    return {"kind": "num", "value": v, "tol": tol, "unit": "pct", "what": what, "label": f"{what}: {v}%"}


def count(v: float, what: str, rel: float = 0.0) -> dict:
    return {"kind": "num", "value": v, "tol": abs(v) * rel, "unit": "count", "what": what, "label": f"{what}: {v:,}"}


def has(regex: str) -> dict:
    return {"kind": "has", "regex": regex, "label": f"mentions /{regex}/"}


def lacks(regex: str) -> dict:
    return {"kind": "lacks", "regex": regex, "label": f"does not say /{regex}/"}


def shows(block_type: str) -> dict:
    return {"kind": "shows", "block": block_type, "label": f"shows a {block_type}"}


def portfolio(*sizes: int) -> dict:
    return {"kind": "portfolio", "sizes": sizes, "label": f"saved portfolio has {' or '.join(map(str, sizes))} TINs"}


def target(v: float) -> dict:
    return {"kind": "target", "value": v, "label": f"saved target is {v:.0%}"}


def chart_scale() -> dict:
    return {"kind": "chart_scale", "label": "percentage charts hold percentage values, not fractions"}


@dataclass
class Turn:
    ask: str
    checks: list[dict] = field(default_factory=list)


@dataclass
class Case:
    id: str
    program: str
    turns: list[Turn]


def one(id: str, program: str, ask: str, *checks: dict) -> Case:
    return Case(id, program, [Turn(ask, list(checks))])


LEAD_FIVE = "10198331, 10211494, 10211501, 10211534 and 10211551"

CASES: list[Case] = [
    # ------------------------------------------------------------------ Part A — LEAD
    one("A1", "LEAD", "How many TINs are in the data, what's the median MLR, and how many are at or under 85%?",
        count(11846, "TINs with a benchmark (11,865 rows in total, 19 with a zero benchmark)"),
        pct(95.8, "median MLR across TINs"), count(834, "TINs with MLR at or under 85%")),
    one("A2", "LEAD", "Compare High vs Low Spending TINs: count, total benchmark, total margin, combined MLR. Show a chart.",
        count(7422, "number of Low Spending TINs"), usd(209.8e9, "Low Spending total benchmark"),
        usd(12.3e9, "Low Spending total margin (savings)"), pct(94.1, "Low Spending combined MLR"),
        count(4443, "number of High Spending TINs"), usd(91.1e9, "High Spending total benchmark"),
        usd(2.1e9, "High Spending total margin (savings)", rel=0.03), pct(97.7, "High Spending combined MLR"),
        shows("chart"), chart_scale()),
    one("A3", "LEAD", "Which 5 TINs have the largest projected savings before risk corridors?",
        has("954373071|Regents"),
        usd(160.9e6, "projected savings before corridors, UC Regents 954373071 (rank 1)"),
        usd(110.7e6, "projected savings before corridors, Sutter Bay 941156581"),
        usd(102.8e6, "projected savings before corridors, DuPage Medical Group 362657618"),
        usd(85.8e6, "projected savings before corridors, Allina 363261413"),
        usd(81.8e6, "projected savings before corridors, IHC Health Services 942854057")),
    Case("A4-A7", "LEAD", [
        Turn(f"I have TINs {LEAD_FIVE}. What is my combined MLR and projected savings? My target is 85%.",
             [pct(97.3, "combined MLR of the five-TIN portfolio"), usd(174.6e6, "portfolio benchmark"),
              usd(169.8e6, "portfolio expense"), usd(4.77e6, "portfolio gross margin (savings before sharing)"),
              count(10044, "portfolio person-years", rel=0.001),
              usd(4.67e6, "net shared savings after corridors and sequestration"),
              usd(-6.90e6, "enhanced PCC repayment (negative: owed back to CMS)"),
              usd(-2.23e6, "projected total monies owed / net settlement (negative: the ACO owes CMS)"),
              # the financial guarantee ($6.32M) is checked offline: the question does not ask for it
              usd(21.4e6, "spending reduction needed to reach the 85% target (the portfolio misses the target)"),
              pct(91.6, "Aged & Disabled cohort MLR"), pct(101.7, "High Needs cohort MLR"), pct(106.6, "ESRD cohort MLR"),
              shows("table"), portfolio(5), target(0.85),
              lacks(r"\bheadroom\b|\bslack\b|portfolio_metrics|run_sql"),
              lacks(r"no double-?counting|because all (five )?TINs show savings")]),
        Turn("Which TINs could I add to bring that portfolio to 85%?",
             [has("910214500|Optum Care Washington"), has("271081647|UNC Physicians"),
              pct(86.2, "combined MLR after adding Optum Care Washington (910214500) only"),
              pct(83.6, "combined MLR after adding both Optum Care Washington and UNC Physicians Network"),
              count(834, "candidate TINs with MLR at or under 85%"),
              portfolio(5), lacks(r"\bheadroom\b|\bslack\b|portfolio_suggest")]),
        Turn("Add those two to my portfolio. What's my MLR now?",
             [pct(83.6, "combined MLR of the seven-TIN portfolio"), usd(111.1e6, "gross margin of the seven-TIN portfolio"),
              portfolio(7)]),
        Turn("Go back to the original five. If projected expense runs 3% hot, what happens?",
             [pct(100.2, "combined MLR of the original five TINs with expense 3% higher"),
              usd(-329e3, "gross margin of the original five with expense 3% higher (negative: a loss)", rel=0.01),
              usd(-336e3, "net shared result of the original five with expense 3% higher (negative: a shared loss)", rel=0.01),
              portfolio(5, 7), target(0.85)]),
    ]),
    # Conditions beyond the suggestion filters: screened with SQL, then handed over as the candidate pool.
    Case("A16", "LEAD", [
        Turn(f"I have TINs {LEAD_FIVE}. My target is 85%.", [portfolio(5), target(0.85)]),
        Turn("Which TINs could I add to reach 85%, looking only at TINs with at least 1,000 PY2027 assigned "
             "beneficiaries, home-health utilization prevalence of 15% or more, and a positive projected net settlement?",
             [count(94, "TINs that pass the three screening conditions", rel=0.03),
              has("832740501|Physicians Services Group"), has("811998432|Healthstone"),
              pct(87.0, "combined MLR after adding every qualifying TIN at or under 85% (the target is not reached)"),
              has(r"(?i)not (be )?reach|cannot reach|can't reach|does not reach|doesn't reach|short of|falls short|not enough|still above|miss"),
              portfolio(5), lacks(r"portfolio_suggest|run_sql|candidate_tins")]),
    ]),
    # A follow-up that leans on a result from two questions back, which is shortened in what the model sees by then.
    Case("A17", "LEAD", [
        Turn(f"I have TINs {LEAD_FIVE}. Which TINs could I add to bring that portfolio to 85%?",
             [has("910214500|Optum Care Washington"), portfolio(5), target(0.85)]),
        Turn('What does the column "ESRD" contain?', [has(r"(?i)label|caption|header|heading")]),
        Turn("Going back to the candidates table you showed for the 85% target: which organization was 20th in that "
             "table, and what were its benchmark and MLR?",
             [has(r"(?i)474717998|Bozeman Health Deaconess"), usd(105.7e6, "benchmark of the 20th candidate in the table"),
              pct(81.8, "MLR of the 20th candidate in the table"),
              lacks(r"(?i)can(no|')t (verify|check|see)|no longer (have|see|available)|recall_result")]),
    ]),
    # A screen that returns more TINs (237) than one query result can list (200): it has to be tightened or ranked.
    Case("A18", "LEAD", [
        Turn(f"I have TINs {LEAD_FIVE}. My target is 85%.", [portfolio(5), target(0.85)]),
        Turn("Which TINs could I add to reach 85%, looking only at TINs with at least 1,000 PY2027 assigned "
             "beneficiaries, home-health utilization prevalence of 10% or more, and a positive projected net settlement?",
             [count(237, "TINs that pass the three screening conditions", rel=0.02),
              has("451444883|(?i)Access Health Care"), has("822410133|(?i)Upperline"),
              count(4, "number of TINs in the plan that reaches the target"),
              pct(84.4, "combined MLR after the additions that reach the target"),
              portfolio(5), lacks(r"portfolio_suggest|run_sql|candidate_tins")]),
    ]),
    # ------------------------------------------------------------------ Part U — unfamiliar questions and follow-ups
    # Questions the prompt and tools were NOT tuned on. Expected values were computed from the raw CSVs with pandas,
    # independently of the app. Do not add prompt rules aimed at these wordings: a failure here should be fixed in
    # tool output or general behaviour, or the case stops measuring anything.
    one("U1", "LEAD", "How many TINs show gross savings but would still owe CMS money at settlement, and what share of "
                      "the TINs with a benchmark is that?",
        count(2689, "TINs with positive gross savings and a negative projected net settlement"),
        pct(22.7, "share of the 11,846 TINs with a benchmark")),
    one("U2", "LEAD", "On average, how much benchmark does a Low Spending TIN get per beneficiary per month compared "
                      "with a High Spending one? Weight it properly.",
        usd(1478.50, "person-year-weighted benchmark PBPM of Low Spending TINs"),
        usd(1938.21, "person-year-weighted benchmark PBPM of High Spending TINs")),
    Case("U3", "LEAD", [
        Turn("Which three organizations have the most High Needs person-years?",
             [has(r"(?i)340714585|Cleveland Clinic"), has(r"(?i)363738206|Endeavor Health"), has(r"(?i)941156581|Sutter Bay")]),
        Turn("Treat those three as my portfolio. What are the combined MLR and gross savings?",
             [pct(96.1, "combined MLR of the three TINs"), usd(170.9e6, "combined gross savings of the three TINs"), portfolio(3)]),
        Turn("What if their costs come in 2% higher than projected?",
             [pct(98.0, "combined MLR with expenses 2% higher"), usd(86.2e6, "gross savings with expenses 2% higher"),
              portfolio(3)]),
        Turn("Forget the 2% scenario. Take Sutter Bay out of my portfolio: what's the combined MLR of the remaining two?",
             [pct(97.7, "base-case combined MLR of Cleveland Clinic and Endeavor Health"), portfolio(2)]),
    ]),
    one("U4", "LEAD", "What is the average age of the beneficiaries in each TIN?",
        has(r"(?i)\b(no|not|isn't|doesn't|does not|cannot|can't|without)\b"), has(r"(?i)\bage\b"),
        lacks(r"(?i)average age (is|of) \d")),
    one("U5", "LEAD", "Which TIN has the lowest MLR, and is there anything about its numbers I should be wary of?",
        has(r"(?i)760528826|Millennium Physicians"), pct(17.7, "MLR of the TIN with the lowest MLR"),
        has(r"(?i)alignment|projected from|trend|person.years|beneficiar|small|tiny|thin")),
    Case("U6", "LEAD", [
        Turn("How many TINs have at least 5,000 PY2027 assigned beneficiaries?",
             [count(645, "TINs with at least 5,000 PY2027 assigned beneficiaries")]),
        Turn("Of those, how many are High Spending?", [count(120, "High Spending TINs among the 645")]),
        Turn("And how does that group's combined MLR compare with the Low Spending ones of the same size?",
             [pct(97.4, "combined MLR of the 120 High Spending TINs with 5,000+ beneficiaries"),
              pct(94.1, "combined MLR of the 525 Low Spending TINs with 5,000+ beneficiaries")]),
    ]),
    Case("U7", "MSSP", [
        Turn("How many TINs are projected to spend more than their benchmark, and what is their combined gross margin?",
             [count(2205, "TINs with projected expenditures above benchmark"),
              usd(-1.395e9, "combined gross margin of those TINs (negative: expenditures exceed benchmark)")]),
        Turn("How many of those would still be over their benchmark if their costs came in 2% lower?",
             [count(1405, "of the 2,205, TINs still above benchmark with expenditures 2% lower")]),
    ]),
    one("U8", "MSSP", "What share of all projected person-years sits in TINs whose expenditures exceed their benchmark?",
        pct(20.8, "share of projected person-years in TINs with MLR above 100%")),
    one("A8", "LEAD", "Which TINs with at least 1,000 beneficiaries have the highest home-health utilization prevalence, "
                      "and what are their MLRs?",
        has("992506226|881934998|MVP Medical|Perpetual Mobile"),
        pct(97.8, "home-health prevalence of the top-ranked TIN (MVP Medical Group 992506226 on the PY2027 assigned-"
                  "beneficiary basis, or Perpetual Mobile Medical Group 881934998 on the 2026 basis)"),
        has(r"(?i)assigned|PY2027|2026"),
        lacks(r"(?i)data (entry )?error|likely (an )?error|data quality (issue|problem)")),
    one("A9", "LEAD", "What share of total person-years is High Needs, and what share is ESRD?",
        pct(18.7, "High Needs share of total person-years"), pct(0.8, "ESRD share of total person-years")),
    one("A10", "LEAD", "What is the quality withhold, the benchmark discount for high- and low-spending ACOs, and the "
                       "first Global corridor threshold?",
        pct(3.0, "quality withhold", tol=0.001), pct(1.75, "benchmark discount for high-spending ACOs", tol=0.001),
        pct(3.0, "benchmark discount for low-spending ACOs", tol=0.001),
        pct(15.0, "first Global corridor threshold, as a share of benchmark", tol=0.001)),
    one("A11", "LEAD", 'What does the column "ESRD" contain?', has(r"(?i)label|caption|header"), has("2024")),
    one("A12", "LEAD", 'What is "Benchmark discount" — a dollar amount?',
        has(r"(?i)\brate\b"), has(r"0\.03\b|\b3(\.0+)?\s*%"), has(r"0\.0175|1\.75\s*%")),
    one("A13", "LEAD", 'Show every TIN whose name contains "Regents of the University of California" with benchmark, '
                       "MLR and shared savings.",
        has("954373071"), has("680344702"),
        usd(1.27e9, "benchmark of TIN 954373071", rel=0.01), pct(87.4, "MLR of TIN 954373071"),
        usd(160.9e6, "shared savings of TIN 954373071"),
        usd(446.8e6, "benchmark of TIN 680344702"), pct(99.3, "MLR of TIN 680344702")),
    one("A14", "LEAD", "Build me a recruiting list: the 20 largest Low-Spending TINs by benchmark with MLR under 90%.",
        has("954373071"),
        usd(1271.3e6, "benchmark of the largest TIN on the list, UC Regents 954373071"),
        pct(87.35, "MLR of UC Regents 954373071", tol=0.05),
        usd(788.3e6, "benchmark of Allina (second on the list)"), pct(89.12, "MLR of Allina", tol=0.05),
        usd(756.1e6, "benchmark of DuPage Medical Group (third on the list)"), pct(86.40, "MLR of DuPage Medical Group", tol=0.05),
        usd(315.4e6, "benchmark of Alegent Creighton Clinic (20th on the list)"),
        pct(88.49, "MLR of Alegent Creighton Clinic", tol=0.05)),
    one("A15", "LEAD", "Chart the median MLR of High Spending versus Low Spending TINs as a bar chart.",
        shows("chart"), chart_scale(),
        pct(97.97, "median MLR of High Spending TINs (97.97% among TINs with a benchmark)", tol=0.06),
        pct(94.41, "median MLR of Low Spending TINs (94.41% among TINs with a benchmark)", tol=0.06)),

    # ------------------------------------------------------------------ Part B — MSSP
    one("B1", "MSSP", "How many TINs, median MLR, how many under 85%, and how many fall in the no-shared-savings band?",
        count(9419, "number of TINs"), pct(95.2, "median MLR"), count(791, "TINs with MLR at or under 85%"),
        count(435, "TINs in the no-shared-savings band")),
    one("B2", "MSSP", "Break the TINs down by savings/losses status with total benchmark and net shared result. Chart it.",
        count(6982, "TINs with status Saving"), usd(156.7e9, "total benchmark of the Saving TINs"),
        usd(7719e6, "net shared result of the Saving TINs (positive)"),
        count(2002, "TINs with status Losses"), usd(36.9e9, "total benchmark of the Losses TINs"),
        usd(-551e6, "net shared result of the Losses TINs (negative: shared losses)"),
        count(435, "TINs with status No Shared Savings"), usd(18.0e9, "total benchmark of the No Shared Savings TINs"),
        shows("chart"), chart_scale()),
    one("B3", "MSSP", "How many TINs exceed the 20% shared-savings cap, and by how much in total?",
        count(53, "TINs whose shared savings exceed the 20% cap"),
        usd(23.7e6, "total amount by which the workbook's uncapped shared savings exceed the cap"),
        has(r"(?i)uncapped|not appl|n.t appl|does not apply|without (the )?cap")),
    Case("B4-B5", "MSSP", [
        Turn("I have TINs 941156581, 363738206 and 340714585. Combined MLR and shared savings under ENHANCED? Target 90%.",
             [pct(98.2, "combined MLR of the three-TIN portfolio"), usd(3.69e9, "portfolio benchmark"),
              usd(3.63e9, "portfolio expense"), usd(67.8e6, "portfolio gross margin"),
              count(231282, "portfolio person-years", rel=0.001),
              usd(50.9e6, "shared savings under ENHANCED (75% sharing, cap not binding)"),
              usd(16.0e6, "financial guarantee"),
              portfolio(3), target(0.90)]),   # cohort MLRs are checked offline; the question does not ask for them
        Turn("Compare LEAD and MSSP for this portfolio.",
             [usd(4.40e9, "benchmark under LEAD"), usd(170.9e6, "gross margin under LEAD"), pct(96.1, "MLR under LEAD"),
              usd(167.5e6, "shared result under LEAD"), usd(3.69e9, "benchmark under MSSP"),
              usd(67.8e6, "gross margin under MSSP"), pct(98.2, "MLR under MSSP"), usd(50.9e6, "shared result under MSSP"),
              shows("table")]),
    ]),
    one("B6", "MSSP", "How many TINs qualify for the Health Equity Benchmark Adjustment, and what's the average "
                      "adjustment per beneficiary for those that do?",
        count(1837, "TINs eligible for the Health Equity Benchmark Adjustment"),
        {"kind": "num", "value": 261.72, "tol": 0.5, "unit": "usd", "label": "average adjustment per beneficiary: $261.72",   # $262 is fine
         "what": "average Health Equity adjustment per beneficiary among eligible TINs, in dollars"}),
    one("B7", "MSSP", "Top 5 TINs by net shared result.",
        has("941156581|Sutter"), usd(70.4e6, "net shared result of Sutter Bay 941156581 (rank 1)"),
        usd(64.6e6, "net shared result of DuPage 362657618 (rank 2)"),
        usd(62.9e6, "net shared result of each of the three UC Regents TINs (954373071, 954415773, 721524529)"),
        has(r"(?i)\bNPI\b|identical|same (figure|value|result)")),
    one("B8", "MSSP", "What's my combined savings if my portfolio is 954373071, 954415773 and 721524529?",
        usd(3.00e9, "portfolio benchmark as computed (it triple-counts one population)", rel=0.01),
        pct(91.6, "portfolio MLR"), has(r"\bNPI\b"),
        has(r"(?i)double|triple|three times|overlap|same (source )?population|count(s|ed|ing)? .{0,40}(more than once|three times)")),
    one("B9", "MSSP", "What are the MSR, the final sharing rate and the shared loss rate in this workbook?",
        pct(0.5, "minimum savings rate (MSR)", tol=0.001), pct(75.0, "final sharing rate", tol=0.001),
        pct(40.0, "shared loss rate", tol=0.001)),
    one("B10", "MSSP", "What does \"Minimum Loss Rate\" mean here — is that the MLR you've been reporting?",
        has(r"(?i)minimum loss rate"), has(r"0\.5\s*%"), has(r"(?i)expen(se|diture)"), has(r"(?i)benchmark")),
    one("B11", "MSSP", "How is the regional adjustment weighted?",
        pct(35.0, "regional adjustment weight when the TIN is below its region", tol=0.001),
        pct(15.0, "regional adjustment weight when the TIN is above its region", tol=0.001),
        count(5382, "TINs below their region (35% weight)"), count(4037, "TINs above their region (15% weight)")),
    one("B12", "MSSP", "For Sutter Bay (941156581), compare MSSP and LEAD.",
        usd(1535.3e6, "Sutter Bay benchmark under MSSP"), pct(93.9, "Sutter Bay MLR under MSSP"),
        usd(70.4e6, "Sutter Bay net shared result under MSSP"), usd(1731.5e6, "Sutter Bay benchmark under LEAD"),
        pct(93.6, "Sutter Bay MLR under LEAD"), usd(110.7e6, "Sutter Bay savings under LEAD: $110.7M gross margin, all of it shared (inside the first "
                     "corridor) before the 2% sequestration; about $108.5M after sequestration")),

    # ------------------------------------------------------------------ Part C — behaviour
    one("C2", "LEAD", "How many TINs are in the no-shared-savings band?",
        has("MSSP"), has(r"(?i)new chat|MSSP (chat|dataset|data)|switch|start"), lacks(r"\b435\b")),
    one("C3", "LEAD", "Which TINs are in Texas?",
        has(r"(?i)state|county|geograph|location|address"), has(r"(?i)\bname")),
    one("C4", "LEAD", "What if the discount were 2% instead of 3%?",
        has(r"(?i)can.t|cannot|not able|unable|not possible|isn.t possible|does not|doesn.t|re-?run|re-?comput"),
        has(r"(?i)stress|expense|benchmark")),
]
