"""Eval cases: TESTING.md as data. Expected values were computed from the raw CSVs, not by the chatbot.

A case is one chat: a program and one or more turns. Each turn has checks on the answer the user would see
(the reply text plus every table / chart / tool line shown under it):

  usd(v)        a dollar figure, ±0.5 % unless rel= is given (matches "$174.6M", "174,608,462", a table cell …)
  pct(v)        a percentage as displayed (97.3 means 97.3 %), ±0.1 point unless tol= is given
  count(v)      an exact count
  has(regex)    the text must match        lacks(regex)   the text must not match
  shows(kind)   a block of that type ("table", "chart") was shown
  portfolio(n)  the saved working portfolio has n TINs (several sizes may be allowed)
  target(v)     the saved target MLR
"""
from __future__ import annotations

from dataclasses import dataclass, field


def usd(v: float, rel: float = 0.005) -> dict:
    return {"kind": "num", "value": v, "tol": abs(v) * rel, "label": f"${v:,.0f}"}


def pct(v: float, tol: float = 0.1) -> dict:
    return {"kind": "num", "value": v, "tol": tol, "label": f"{v}%"}


def count(v: float, rel: float = 0.0) -> dict:
    return {"kind": "num", "value": v, "tol": abs(v) * rel, "label": f"{v:,}"}


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
        count(11846), pct(95.8), count(834)),
    one("A2", "LEAD", "Compare High vs Low Spending TINs: count, total benchmark, total margin, combined MLR. Show a chart.",
        count(7422), usd(209.8e9), usd(12.3e9), pct(94.1), count(4443), usd(91.1e9), usd(2.1e9, rel=0.03), pct(97.7),
        shows("chart")),
    one("A3", "LEAD", "Which 5 TINs have the largest projected savings before risk corridors?",
        has("954373071|Regents"), usd(160.9e6), usd(110.7e6), usd(102.8e6), usd(85.8e6), usd(81.8e6)),
    Case("A4-A7", "LEAD", [
        Turn(f"I have TINs {LEAD_FIVE}. What is my combined MLR and projected savings? My target is 85%.",
             [pct(97.3), usd(174.6e6), usd(169.8e6), usd(4.77e6), count(10044, rel=0.001), usd(4.67e6), usd(6.90e6),
              usd(2.23e6), usd(6.32e6), usd(21.4e6), pct(91.6), pct(101.7), pct(106.6), shows("table"),
              portfolio(5), target(0.85), lacks(r"\bheadroom\b|\bslack\b|portfolio_metrics|run_sql")]),
        Turn("Which TINs could I add to bring that portfolio to 85%?",
             [has("910214500|Optum Care Washington"), has("271081647|UNC Physicians"), pct(86.2), pct(83.6), count(834),
              portfolio(5), lacks(r"\bheadroom\b|\bslack\b|portfolio_suggest")]),
        Turn("Add those two to my portfolio. What's my MLR now?",
             [pct(83.6), usd(111.1e6), portfolio(7)]),
        Turn("Go back to the original five. If projected expense runs 3% hot, what happens?",
             [pct(100.2), usd(329e3, rel=0.01), usd(336e3, rel=0.01), portfolio(5, 7), target(0.85)]),
    ]),
    one("A8", "LEAD", "Which TINs with at least 1,000 beneficiaries have the highest home-health utilization prevalence, "
                      "and what are their MLRs?",
        has("992506226|881934998|MVP Medical|Perpetual Mobile"), pct(97.8), has(r"(?i)assigned|PY2027|2026"),
        lacks(r"(?i)data (entry )?error|likely (an )?error|data quality (issue|problem)")),
    one("A9", "LEAD", "What share of total person-years is High Needs, and what share is ESRD?", pct(18.7), pct(0.8)),
    one("A10", "LEAD", "What is the quality withhold, the benchmark discount for high- and low-spending ACOs, and the "
                       "first Global corridor threshold?",
        has(r"\b3(\.0+)?\s*%"), has(r"1\.75\s*%"), has(r"\b15(\.0+)?\s*%")),
    one("A11", "LEAD", 'What does the column "ESRD" contain?', has(r"(?i)label|caption|header"), has("2024")),
    one("A12", "LEAD", 'What is "Benchmark discount" — a dollar amount?',
        has(r"(?i)\brate\b"), has(r"0\.03\b|\b3(\.0+)?\s*%"), has(r"0\.0175|1\.75\s*%")),
    one("A13", "LEAD", 'Show every TIN whose name contains "Regents of the University of California" with benchmark, '
                       "MLR and shared savings.",
        has("954373071"), has("680344702"), usd(1.27e9, rel=0.01), pct(87.4), usd(160.9e6),
        usd(446.8e6), pct(99.3)),
    one("A14", "LEAD", "Build me a recruiting list: the 20 largest Low-Spending TINs by benchmark with MLR under 90%.",
        has("954373071"), usd(1271.3e6), pct(87.35, tol=0.05), usd(788.3e6), pct(89.12, tol=0.05), usd(756.1e6),
        pct(86.40, tol=0.05), usd(315.4e6), pct(88.49, tol=0.05)),

    # ------------------------------------------------------------------ Part B — MSSP
    one("B1", "MSSP", "How many TINs, median MLR, how many under 85%, and how many fall in the no-shared-savings band?",
        count(9419), pct(95.2), count(791), count(435)),
    one("B2", "MSSP", "Break the TINs down by savings/losses status with total benchmark and net shared result. Chart it.",
        count(6982), usd(156.7e9), usd(7719e6), count(2002), usd(36.9e9), usd(551e6), count(435), usd(18.0e9),
        shows("chart")),
    one("B3", "MSSP", "How many TINs exceed the 20% shared-savings cap, and by how much in total?",
        count(53), usd(23.7e6), has(r"(?i)uncapped|not appl|n.t appl|does not apply|without (the )?cap")),
    Case("B4-B5", "MSSP", [
        Turn("I have TINs 941156581, 363738206 and 340714585. Combined MLR and shared savings under ENHANCED? Target 90%.",
             [pct(98.2), usd(3.69e9), usd(3.63e9), usd(67.8e6), count(231282, rel=0.001), usd(50.9e6), usd(16.0e6),
              portfolio(3), target(0.90)]),   # cohort MLRs are checked offline; the question does not ask for them
        Turn("Compare LEAD and MSSP for this portfolio.",
             [usd(4.40e9), usd(170.9e6), pct(96.1), usd(167.5e6), usd(3.69e9), usd(67.8e6), pct(98.2), usd(50.9e6),
              shows("table")]),
    ]),
    one("B6", "MSSP", "How many TINs qualify for the Health Equity Benchmark Adjustment, and what's the average "
                      "adjustment per beneficiary for those that do?",
        count(1837), {"kind": "num", "value": 261.72, "tol": 0.02, "label": "$261.72"}),
    one("B7", "MSSP", "Top 5 TINs by net shared result.",
        has("941156581|Sutter"), usd(70.4e6), usd(64.6e6), usd(62.9e6), has(r"(?i)\bNPI\b|identical|same (figure|value|result)")),
    one("B8", "MSSP", "What's my combined savings if my portfolio is 954373071, 954415773 and 721524529?",
        usd(3.00e9, rel=0.01), pct(91.6), has(r"\bNPI\b"),
        has(r"(?i)double|triple|three times|overlap|same (source )?population|count(s|ed|ing)? .{0,40}(more than once|three times)")),
    one("B9", "MSSP", "What are the MSR, the final sharing rate and the shared loss rate in this workbook?",
        has(r"0\.5\s*%"), has(r"\b75(\.0+)?\s*%"), has(r"\b40(\.0+)?\s*%"), has(r"(?i)enhanced")),
    one("B10", "MSSP", "What does \"Minimum Loss Rate\" mean here — is that the MLR you've been reporting?",
        has(r"(?i)minimum loss rate"), has(r"0\.5\s*%"), has(r"(?i)expen(se|diture)"), has(r"(?i)benchmark")),
    one("B11", "MSSP", "How is the regional adjustment weighted?",
        has(r"\b35(\.0+)?\s*%"), has(r"\b15(\.0+)?\s*%"), count(5382), count(4037)),
    one("B12", "MSSP", "For Sutter Bay (941156581), compare MSSP and LEAD.",
        usd(1535.3e6), pct(93.9), usd(70.4e6), usd(1731.5e6), pct(93.6), usd(110.7e6)),

    # ------------------------------------------------------------------ Part C — behaviour
    one("C2", "LEAD", "How many TINs are in the no-shared-savings band?",
        has("MSSP"), has(r"(?i)new chat|MSSP (chat|dataset|data)|switch|start"), lacks(r"\b435\b")),
    one("C3", "LEAD", "Which TINs are in Texas?",
        has(r"(?i)state|county|geograph|location|address"), has(r"(?i)\bname")),
    one("C4", "LEAD", "What if the discount were 2% instead of 3%?",
        has(r"(?i)can.t|cannot|not able|unable|not possible|isn.t possible|does not|doesn.t|re-?run|re-?comput"),
        has(r"(?i)stress|expense|benchmark")),
]
