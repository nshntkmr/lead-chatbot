"""Grading for the chat cases.

Two passes, because neither is enough alone for financial answers:

1. Deterministic (`grade`): is the expected figure shown at all, and where its sign is explicit (a table or
   chart cell, or prose written with a minus sign or parentheses) is the sign right? Cheap and repeatable, but
   it cannot tell which metric a number belongs to, and prose such as "the ACO owes CMS $2.23M" carries its
   sign in words.
2. Model judge (`judge`): reads the question, the reply and the tables/charts the user saw, and decides for
   each expected fact whether the answer states that value for that metric, entity and basis with the right
   sign, and whether the prose contradicts the tables. A fact passes only if both passes accept it.

`JUDGE_SELFTESTS` are answers that must be rejected (a flipped sign, prose contradicting its table, a figure
attached to the wrong cohort) and one that must be accepted; the runner checks the judge against them on every
run, so a judge that has gone lenient shows up as a failure rather than as green cases.
"""
from __future__ import annotations

import json
import re

_NUM = re.compile(r"(?P<neg>[-−–]|\(\s?)?\$?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
                  r"(?P<suf>%|[kKmMbB]\b|bn\b|million\b|billion\b|thousand\b)?(?P<close>\s?\))?")
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def numbers_in(text: str) -> list[tuple[float, bool]]:
    """Every figure in prose as (value, sign_is_explicit). $1.2M / 1.2 million / 1,200,000 all read as 1200000.
    A leading minus or accounting parentheses make the value negative and its sign explicit; anything else is
    read as positive with the sign not explicit (prose often says "owes $2M" for a negative amount)."""
    out = []
    text = text.replace("*", "")
    for m in _NUM.finditer(text):
        start = m.start("num")
        if start and (text[start - 1].isalnum() or text[start - 1] in "._"):   # part of a word, id or decimal
            continue
        v = float(m.group("num").replace(",", "")) * _SCALE.get((m.group("suf") or "").lower(), 1)
        neg = m.group("neg") or ""
        if neg.startswith("("):
            # accounting negative, dollars only: "($2.23M)". "(87.4%)" is just a parenthesis.
            negative = bool(m.group("close")) and "$" in m.group(0)
        else:
            # A minus sign directly before the figure, and not joined to what precedes it: "85–100%",
            # "2024-2026" and "COVID-19" are not negatives; "MLR – 97.3%" (spaced dash) is a separator.
            # A markdown bullet ("- 5,382 TINs") is not a minus either: the sign must touch the figure.
            prev = text[m.start() - 1] if m.start() else " "
            touching = bool(neg) and text[m.end("neg")] in "$0123456789"
            negative = touching and not (prev.isalnum() or prev == "%")
        out.append((-v if negative else v, negative))
    return out


def visible(text: str, blocks: list[dict]) -> tuple[str, list[tuple[float, bool]]]:
    """What the user sees for one answer: all of its text, and every number in the text, tables and charts.
    Numbers from table and chart cells keep their sign and are marked sign-explicit."""
    parts, nums = [text], []
    for b in blocks:
        parts += [str(b.get(k) or "") for k in ("title", "subtitle", "label", "detail")]
        for row in b.get("rows") or []:
            for v in row:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums.append((float(v), True))
                elif isinstance(v, str):
                    parts.append(v)
        for ds in b.get("datasets") or []:
            for v in ds.get("data") or []:
                v = v.get("y") if isinstance(v, dict) else v
                if isinstance(v, (int, float)):
                    nums.append((float(v), True))
        parts += [str(x) for x in b.get("labels") or []]
    full = "\n".join(parts)
    return full, nums + numbers_in(full)


def grade(check: dict, text: str, nums: list[tuple[float, bool]], blocks: list[dict], state: dict) -> tuple[bool, str]:
    """The deterministic pass for one check: (passed, detail)."""
    kind = check["kind"]
    if kind == "num":
        want, tol = check["value"], check["tol"] + 1e-9
        close = [(v, explicit) for v, explicit in nums if abs(abs(v) - abs(want)) <= tol]
        if not close:
            near = min((v for v, _ in nums), key=lambda v: abs(abs(v) - abs(want)), default=None)
            return False, f"closest figure shown: {near:,.6g}" if near is not None else "no figures shown"
        if want != 0 and not any((v < 0) == (want < 0) for v, explicit in close if explicit) \
                and all(explicit for _, explicit in close):
            return False, f"shown only with the opposite sign ({close[0][0]:,.6g})"
        return True, ""
    if kind == "has":
        return bool(re.search(check["regex"], text)), ""
    if kind == "lacks":
        m = re.search(check["regex"], text)
        return not m, f"found {m.group(0)!r}" if m else ""
    if kind == "shows":
        return any(b.get("type") == check["block"] for b in blocks), ""
    if kind == "portfolio":
        n = len(state.get("portfolio") or [])
        return n in check["sizes"], f"has {n}"
    if kind == "target":
        got = state.get("target_mlr")
        return got is not None and abs(got - check["value"]) < 1e-9, f"is {got}"
    if kind == "chart_scale":
        for b in blocks:
            if b.get("type") != "chart":
                continue
            vals = [abs(v.get("y") if isinstance(v, dict) else v) for ds in b.get("datasets") or [] for v in ds.get("data") or []
                    if isinstance(v.get("y") if isinstance(v, dict) else v, (int, float))]
            labels = " ".join([b.get("title") or "", b.get("y_label") or ""] + [ds.get("label") or "" for ds in b.get("datasets") or []])
            if b.get("value_format") == "percent" and b.get("percent_scale") != "percent":
                return False, "a percent chart without percent_scale would be drawn ×100"
            # An MLR is never under 2 %: values that small on an MLR axis are fractions, however they are formatted.
            if vals and re.search(r"(?i)\bMLR\b", labels) and max(vals) <= 2:
                return False, f"chart '{b.get('title')}' plots MLR as fractions (max {max(vals):g})"
        return True, ""
    raise ValueError(kind)


# ---------------------------------------------------------------------------------------------------- judge
JUDGE_SYSTEM = """You grade answers from a financial analytics assistant used by actuaries and CFOs. You are \
strict: a wrong number in front of these readers is costly, and an answer that only looks right must not pass.

You get the user's question, the assistant's reply, the tables and charts shown with it (the user sees those \
in full, so a value that appears only in a table counts as stated), and a numbered list of expected facts.

For each expected fact give one verdict:
- correct: the answer states this value for THIS metric, entity and basis, within the tolerance, with the right \
sign or direction. Ordinary rounding is fine ($4.77M for 4,765,803; 97.3% for 0.9727). Direction may be in \
words: "the ACO owes CMS $2.2M", "a loss of $329k", "misses the target by $21M" are negative or shortfall \
statements; "CMS pays the ACO", "savings of" are positive.
- wrong: the answer gives a different value for this metric; or the right magnitude with the wrong sign or \
direction; or the expected number appears but attached to a different metric, entity, cohort, year or basis. \
If the prose states a different value for this metric than the expected one, the fact is wrong even when a \
table or chart shows the expected value: the reader is told the wrong number.
- missing: the answer does not state this metric at all.

Then report two further lists.

contradictions: only numeric ones. The reply gives two materially different numbers for the SAME metric of the \
SAME entity on the SAME basis: prose against a table or chart, or one sentence against another. Quote both \
numbers. These are not contradictions: rounding; a figure before and after sharing, corridors, caps or \
sequestration when the reply distinguishes them; a what-if or stress-test figure beside a base-case figure; \
figures for different TINs, cohorts, programs or years; a table sorted or limited differently from how the \
prose describes it. When in doubt, it is not a contradiction.

observations: anything else that looks WRONG to a careful reviewer (a count or description that does not \
match a table row, a claim the figures shown contradict, a malformed number). These are recorded for a human \
to read and do not fail the answer. Record problems only: never things you checked that turned out consistent, \
and never that something cannot be verified from the reply. An empty list is the normal case for both."""

GRADE_TOOL = {
    "name": "grade",
    "description": "Record the verdict for every expected fact and any contradictions inside the answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "integer"},
                "verdict": {"type": "string", "enum": ["correct", "wrong", "missing"]},
                "evidence": {"type": "string", "description": "The words or table cell the verdict rests on, quoted briefly"}},
                "required": ["id", "verdict", "evidence"]}},
            "contradictions": {"type": "array", "items": {"type": "string"}},
            "observations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["facts", "contradictions", "observations"],
    },
}


def _fact_line(i: int, c: dict) -> str:
    v, tol = c["value"], c["tol"]
    if c.get("unit") == "pct":
        val, t = f"{v:g}%", f"±{tol:.3g} percentage points"
    elif c.get("unit") == "usd":
        val, t = f"{'-' if v < 0 else ''}${abs(v):,.2f}".replace(".00", ""), f"±${tol:,.0f}" if tol >= 1 else f"±${tol:.2f}"
    else:
        val, t = f"{v:,.6g}", f"±{tol:,.6g}" if tol else "exact"
    return f"{i}. {c['what']} = {val} ({t})"


def render_blocks(blocks: list[dict], max_rows: int = 40) -> str:
    """Tables and charts as text for the judge (long tables: first rows and the last one, usually the TOTAL)."""
    out = []
    for b in blocks:
        if b.get("type") == "table":
            rows = b.get("rows") or []
            shown = rows if len(rows) <= max_rows else rows[:max_rows - 1] + [["…"], rows[-1]]
            out.append(f"TABLE: {b.get('title', '')}\n{b.get('subtitle', '')}\n" + " | ".join(map(str, b.get("columns") or []))
                       + "\n" + "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in shown))
        elif b.get("type") == "chart":
            lines = [f"CHART ({b.get('chart_type')}): {b.get('title', '')}; y axis: {b.get('y_label', '')}; "
                     f"values formatted as {b.get('value_format', 'number')}"]
            labels = b.get("labels") or []
            for ds in b.get("datasets") or []:
                data = ds.get("data") or []
                pts = [f"{labels[i] if i < len(labels) else i}: {v}" for i, v in enumerate(data[:max_rows])]
                lines.append(f"  series {ds.get('label')}: " + "; ".join(pts))
            out.append("\n".join(lines))
    return "\n\n".join(out)


async def judge(client, model: str, ask: str, answer: str, blocks: list[dict], checks: list[dict]) -> dict:
    """Ask the model to grade the numeric facts of one turn. Returns {"verdicts": {index in checks: (verdict,
    evidence)}, "contradictions": [...], "usage": message.usage}."""
    facts = [(i, c) for i, c in enumerate(checks) if c["kind"] == "num"]
    listing = "\n".join(_fact_line(n, c) for n, (_, c) in enumerate(facts, 1)) or "(none)"
    content = (f"QUESTION\n{ask}\n\nASSISTANT REPLY\n{answer or '(empty)'}\n\nTABLES AND CHARTS SHOWN\n"
               f"{render_blocks(blocks) or '(none)'}\n\nEXPECTED FACTS\n{listing}")
    # Forced tool choice is not available on every model, so the instruction asks for the call and a reply
    # without one is retried once.
    content += "\n\nRecord your grading by calling the grade tool exactly once. Do not reply in text."
    data, msg = {}, None
    for _ in range(2):
        msg = await client.messages.create(model=model, max_tokens=4000, system=JUDGE_SYSTEM, tools=[GRADE_TOOL],
                                           messages=[{"role": "user", "content": content}])
        data = next((b.input for b in msg.content if b.type == "tool_use" and b.name == "grade"), None) or {}
        if data:
            break
    verdicts = {}
    for f in data.get("facts") or []:
        n = f.get("id")
        if isinstance(n, int) and 1 <= n <= len(facts):
            verdicts[facts[n - 1][0]] = (f.get("verdict", "missing"), f.get("evidence", ""))
    return {"verdicts": verdicts, "contradictions": [str(x) for x in data.get("contradictions") or []],
            "observations": [str(x) for x in data.get("observations") or []], "usage": msg}


# Answers the judge must get right. `expect` maps the 1-based fact number to the verdicts that are acceptable;
# `contradiction` says whether the judge must report one.
_PORTFOLIO_TABLE = {"type": "table", "title": "LEAD portfolio: 5 TINs · MLR 97.3%", "subtitle": "Benchmark $174.6M · expense $169.8M",
                    "columns": ["TIN", "Organization", "Benchmark $", "Expense $", "Gross margin $", "MLR %"],
                    "rows": [["TOTAL", "5 TINs", 174608462, 169842659, 4765803, 97.27]]}
_F_MLR = {"kind": "num", "value": 97.3, "tol": 0.1, "unit": "pct", "what": "combined MLR of the five-TIN portfolio"}
_F_OWED = {"kind": "num", "value": -2.23e6, "tol": 11150, "unit": "usd",
           "what": "projected total monies owed / net settlement (negative: the ACO owes CMS)"}
_F_HN = {"kind": "num", "value": 101.7, "tol": 0.1, "unit": "pct", "what": "High Needs cohort MLR"}

JUDGE_SELFTESTS = [
    {"name": "accepts a correct answer (sign given in words)",
     "ask": "What is my combined MLR and projected settlement?",
     "answer": "Your combined MLR is 97.3%. After the enhanced PCC repayment the projected settlement is that the ACO "
               "owes CMS about $2.23M. The High Needs cohort runs at 101.7%.",
     "blocks": [_PORTFOLIO_TABLE], "checks": [_F_MLR, _F_OWED, _F_HN],
     "expect": {1: {"correct"}, 2: {"correct"}, 3: {"correct"}}, "contradiction": False},
    {"name": "rejects a flipped sign (payment to the ACO instead of owed to CMS)",
     "ask": "What is my combined MLR and projected settlement?",
     "answer": "Your combined MLR is 97.3%. The projected settlement is a payment of $2.23M from CMS to the ACO.",
     "blocks": [_PORTFOLIO_TABLE], "checks": [_F_MLR, _F_OWED],
     "expect": {1: {"correct"}, 2: {"wrong"}}, "contradiction": False},
    {"name": "rejects prose that contradicts its own table (20% MLR in prose, 97.27 in the table)",
     "ask": "What is my combined MLR?",
     "answer": "Your combined MLR is 20%, comfortably under your 85% target.",
     "blocks": [_PORTFOLIO_TABLE], "checks": [_F_MLR],
     "expect": {1: {"wrong"}}, "contradiction": True},
    {"name": "rejects the right number on the wrong cohort (101.7% given for ESRD, not High Needs)",
     "ask": "What are my cohort MLRs?",
     "answer": "By cohort: Aged & Disabled 91.6%, ESRD 101.7%. High Needs was not broken out.",
     "blocks": [], "checks": [_F_HN],
     "expect": {1: {"wrong", "missing"}}, "contradiction": False},
]


async def judge_selftest(client, model: str) -> tuple[list[tuple[str, bool, str]], list]:
    """Run the judge on JUDGE_SELFTESTS. Returns ((name, passed, detail) rows, usage messages)."""
    rows, usages = [], []
    for t in JUDGE_SELFTESTS:
        r = await judge(client, model, t["ask"], t["answer"], t["blocks"], t["checks"])
        usages.append(r["usage"])
        problems = []
        for n, allowed in t["expect"].items():
            got = r["verdicts"].get(n - 1, ("missing", ""))[0]
            if got not in allowed:
                problems.append(f"fact {n}: judged {got}, should be {' or '.join(sorted(allowed))}")
        if t["contradiction"] and not r["contradictions"]:
            problems.append("did not report the contradiction between prose and table")
        rows.append((t["name"], not problems, "; ".join(problems)))
    return rows, usages


def deterministic_selftest() -> list[tuple[str, bool, str]]:
    """The deterministic pass on known-bad answers; no model calls."""
    rows = []

    def expect(name: str, ok: bool, want: bool, detail: str) -> None:
        rows.append((name, ok == want, f"deterministic pass returned {ok} ({detail or 'no detail'}), expected {want}"))

    table_pos = [{"type": "table", "columns": ["Measure", "USD"], "rows": [["Total monies owed", 2230000.0]]}]
    table_neg = [{"type": "table", "columns": ["Measure", "USD"], "rows": [["Total monies owed", -2230000.0]]}]
    for name, text, blocks, want in (
            ("grader: +$2.23M in a table fails a check expecting −$2.23M", "Settlement below.", table_pos, False),
            ("grader: −$2.23M in a table passes", "Settlement below.", table_neg, True),
            ("grader: prose '-$2.23M' passes", "Total monies owed is -$2.23M.", [], True),
            ("grader: prose '($2.23M)' passes", "Total monies owed is ($2.23M).", [], True),
            ("grader: prose '+$2.23M' written with an explicit minus elsewhere is not confused by a range",
             "MLR is in the 85–100% range and the settlement is −$2.23M.", [], True)):
        full, nums = visible(text, blocks)
        ok, detail = grade(_F_OWED, full, nums, blocks, {})
        expect(name, ok, want, detail)
    full, nums = visible("The range is 85–100%.", [])
    rows.append(("grader: a range '85–100%' is not read as −100", (-100.0, True) not in nums, f"numbers read: {nums}"))
    full, nums = visible("Weights:\n- 5,382 TINs get the 35% weight.\n– 4,037 TINs get 15%.", [])
    rows.append(("grader: a bullet '- 5,382 TINs' is not read as −5,382",
                 (5382.0, False) in nums and (4037.0, False) in nums, f"numbers read: {nums}"))
    frac = [{"type": "chart", "title": "Median MLR by class", "value_format": "number", "y_label": "MLR",
             "datasets": [{"label": "Median MLR", "data": [0.9797, 0.9441]}], "labels": ["High", "Low"]}]
    good = [{"type": "chart", "title": "Median MLR by class", "value_format": "percent", "percent_scale": "percent",
             "y_label": "MLR %", "datasets": [{"label": "Median MLR %", "data": [97.97, 94.41]}], "labels": ["High", "Low"]}]
    expect("grader: an MLR chart plotted as fractions fails chart_scale", grade({"kind": "chart_scale"}, "", [], frac, {})[0], False, "")
    expect("grader: an MLR chart in percentage values passes chart_scale", grade({"kind": "chart_scale"}, "", [], good, {})[0], True, "")
    return rows
