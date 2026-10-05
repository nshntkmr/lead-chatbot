"""Claude agent: system prompt, tools, and the streaming tool-use loop."""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import logging
import os
from typing import AsyncIterator

from anthropic import AsyncAnthropic, BadRequestError

from . import config
from .data import Warehouse, fit_rows
from .portfolio import PortfolioCalc, PortfolioUnavailable, build_spec, clean_tins, compare_programs

log = logging.getLogger(__name__)

CHART_TYPES = ["bar", "horizontal_bar", "stacked_bar", "line", "area", "scatter", "pie", "doughnut"]
VALUE_FORMATS = ["number", "currency", "percent", "ratio"]

TOOLS = [
    {
        "name": "search_columns",
        "description": (
            "Find columns by keyword across the data tables, and look up definitions in the column dictionary. "
            "Returns exact column names with type, the linked dictionary definition/units/notes/formula when there is "
            "one, related dictionary entries for the keywords, and a quick profile: non-null count and min/max/mean "
            "for numbers, or top values for text. Use it whenever you are not certain which column answers "
            "the question, or to see what values a text column holds before filtering on it."),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "Space-separated keywords, e.g. 'benchmark PBPM HN 2027'"},
                "table": {"type": "string", "description": "Optional table name to restrict the search"},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run one read-only DuckDB SELECT query and get the result back (max 200 rows; fewer when rows are "
            "wide, so select only the columns you need). Use this to compute every number you report. Quote "
            "identifiers with double quotes."),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "purpose": {"type": "string", "description": "Short plain-English label shown to the user, e.g. 'Average benchmark by alignment type'"},
            },
            "required": ["sql", "purpose"],
        },
    },
    {
        "name": "create_chart",
        "description": (
            "Show the user an interactive chart. You give a SELECT query; the app runs it and plots the result, "
            "so chart values are always real. Keep categories readable (≤ 30 bars, ≤ 12 pie slices; use ORDER BY "
            "and LIMIT). For histograms, bin in SQL (e.g. floor(x/1000)*1000 AS bucket) and use a bar chart. "
            "You receive the plotted rows back so you can describe the chart accurately."),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "chart_type": {"type": "string", "enum": CHART_TYPES},
                "sql": {"type": "string"},
                "x": {"type": "string", "description": "Result column for the x-axis / category labels / pie slice labels"},
                "y": {"type": "array", "items": {"type": "string"}, "description": "One or more numeric result columns (one series each)"},
                "point_label": {"type": "string", "description": "Scatter only: optional result column shown in the tooltip (e.g. Organization)"},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "value_format": {"type": "string", "enum": VALUE_FORMATS, "description": "How to format y values. 'percent' expects percentage values, as the SQL should "
                                                                                    "return them with round(100 * x, 2): 87.35 → 87.35%. Never fractions."},
            },
            "required": ["title", "chart_type", "sql", "x", "y"],
        },
    },
    {
        "name": "show_table",
        "description": (
            "Show the user a sortable table (up to 2,000 rows) with a CSV download button. Use for lists longer "
            "than ~10 rows or when the user asks to see/export records. Don't repeat the table in your reply."),
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "sql": {"type": "string"}},
            "required": ["title", "sql"],
        },
    },
    {
        "name": "portfolio_metrics",
        "description": (
            "Combined financials for a set of TINs treated as one ACO: person-years, beneficiaries, benchmark $, "
            "expense $, gross margin (savings) $, combined MLR (= total expense / total benchmark, NOT an average of "
            "TIN MLRs), shared savings after the Global risk corridors, sequestration, enhanced PCC repayment, and a "
            "cohort split (A&D / High Needs / ESRD). Also maintains the user's working portfolio for this chat: "
            "action 'set' replaces it with these TINs, 'add'/'remove' change it, 'current' reports the saved one. "
            "Use 'add'/'remove' with save=false for a what-if that should not change the working portfolio. "
            "Pass target_mlr to get the room under (or shortfall to) a target. expense_change_pct / benchmark_change_pct run a "
            "stress test (what if costs run 3% hot). Also returns the financial guarantee, quality withhold at risk and "
            "a loss figure with a note saying what it is (LEAD: the shared loss in an illustrative scenario where losses "
            "equal the whole benchmark, not a maximum; MSSP: the capped maximum shared loss). Use this tool for the "
            "combined figures whenever the user asks about 'my TINs', a list of TINs, the effect of adding/removing "
            "TINs, or a what-if on their portfolio. The TIN list may come from a run_sql screen on any column."),
        "input_schema": {
            "type": "object",
            "properties": {
                "tins": {"type": "array", "items": {"type": "string"}, "description": "TIN identifiers (digits). Not needed for action 'current'."},
                "action": {"type": "string", "enum": ["set", "add", "remove", "current"], "description": "Default 'set'"},
                "save": {"type": "boolean", "description": "Default true. false = what-if only, keep the saved portfolio unchanged."},
                "target_mlr": {"type": "number", "description": "Optional MLR target as a fraction, e.g. 0.85"},
                "expense_change_pct": {"type": "number", "description": "Stress test: change every TIN's projected expense by this percent (e.g. 3 = 3% higher, -2 = 2% lower). Use with save=false."},
                "benchmark_change_pct": {"type": "number", "description": "Stress test: change every TIN's benchmark by this percent. Use with save=false."},
            },
            "required": [],
        },
    },
    {
        "name": "portfolio_suggest",
        "description": (
            "Which TINs to add or drop to reach or stay within an MLR target. Given the working portfolio (or an "
            "explicit TIN list) and a target MLR, returns: the current room under the target; the fewest TINs to "
            "REMOVE to meet it; the fewest TINs to ADD to meet it; and screened candidate TINs that can be added "
            "without breaking it (largest by benchmark and by margin), with optional filters. Exact and deterministic: "
            "room under target = target × benchmark $ − expense $, and a set meets the target when it sums to ≥ 0. "
            "Use it for questions like 'which TINs can I include and stay under 85%'. Say the target in the answer."),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_mlr": {"type": "number", "description": "MLR target as a fraction, e.g. 0.85"},
                "tins": {"type": "array", "items": {"type": "string"}, "description": "Optional. Defaults to the working portfolio."},
                "exclude_tins": {"type": "array", "items": {"type": "string"}},
                "candidate_tins": {"type": "array", "items": {"type": "string"},
                                   "description": "Optional. Limit the candidates to these TINs. Use it when the user's "
                                                  "conditions go beyond the filters below (beneficiary counts, prevalence, "
                                                  "settlement, claims…): screen with run_sql first, then pass the TINs here."},
                "name_like": {"type": "string", "description": "Only candidates whose organization name contains this text"},
                "spending_class": {"type": "string", "enum": ["High Spending ACO", "Low Spending ACO"]},
                "min_person_years": {"type": "number"},
                "max_person_years": {"type": "number"},
                "limit": {"type": "integer", "description": "Candidates per list (default 25, max 100)"},
            },
            "required": ["target_mlr"],
        },
    },
    {
        "name": "recall_result",
        "description": (
            "Read again, in full, the result of a tool call made earlier in this chat. Results from earlier questions "
            "are shortened in what you see and end with their result id. Use this whenever a follow-up depends on "
            "details of an earlier result (a candidate list, per-TIN rows, a scenario's figures) before you rely on "
            "them, instead of working from the shortened text or saying they can no longer be checked."),
        "input_schema": {
            "type": "object",
            "properties": {"result_id": {"type": "string", "description": "The id given at the end of the shortened result"}},
            "required": ["result_id"],
        },
    },
]

COMPARE_TOOL = {
    "name": "compare_programs",
    "description": (
        "Side-by-side headline figures for the same TINs under every program dataset loaded in this app (e.g. LEAD "
        "vs MSSP): person-years, benchmark $, expense $, gross margin, MLR and the shared result under each program's "
        "own sharing rules, combined and per TIN. Use it when the user asks which program is better for a TIN or "
        "portfolio, or how the two models compare. Defaults to the working portfolio when tins are omitted."),
    "input_schema": {
        "type": "object",
        "properties": {"tins": {"type": "array", "items": {"type": "string"}}},
        "required": [],
    },
}

SYSTEM_TEMPLATE = """You are {app_name}, a data analyst assistant inside a company web app. Business users ask \
questions in plain English; you answer them from the data tables described below by querying them with tools.
{program_intro}

# How to work
1. Every number you state must come from a query you ran in this conversation (run_sql, create_chart or \
show_table) or from a '= value' constant shown in the schema below. Never estimate, recall or invent values. \
If a query fails, fix it and retry. Results from earlier questions are shortened in what you see: when an answer \
depends on details of one, read it again with recall_result rather than working from the fragment.
2. Column names are long and contain spaces and symbols such as | [ ] ! — always wrap them in double quotes \
exactly as listed, e.g. "Expenditure PBPM | HN | BY2 2025". Wrap table names in double quotes too.
3. If you are not sure which column answers the question, call search_columns first. It returns each column's \
curated note (with a kind: duplicate / raw / parameter / metric / label) and data-dictionary definition when there is \
one, plus related dictionary entries. A note marked 'duplicate' names the canonical column to prefer. Use those definitions (and the \
domain notes below) when explaining what a number means. When several columns could fit, pick the most likely one, \
name it in your answer, and mention the alternative.
4. ID columns such as TIN and NPI are text: compare as strings, e.g. WHERE "TIN" = '10198331'. Organization \
names: match with ILIKE '%name%' and confirm the match before answering.
5. Aggregate in SQL instead of pulling raw rows; results give you at most 200 rows, and fewer when the rows are \
wide — never SELECT * from these tables.
6. Use create_chart when a ranking, comparison, distribution or trend is easier to see than read, and always when \
the user asks for a chart or graph. Use show_table for lists longer than ~10 rows or when the user wants to export; \
the user sees the whole table, so don't repeat it in text.
7. Style: lead with the direct answer in one to three sentences, then brief supporting detail. Money like \
$1,234,567; percentages with one decimal. Markdown tables only for small results (≤ 10 rows). End with a short \
"*Based on:* column names" line when the columns used aren't obvious. Don't narrate your tool calls. Before you \
finish, read each summary sentence against the figures you are showing: words like all, each, none, identical, above, \
below, largest, and any count or description of a table must be true of the rows the user sees, and a number you \
copy into a table must match the query result digit for digit.
8. If the data can't answer the question, say so plainly and say what would be needed. If a question is ambiguous, \
answer the most reasonable reading and state the assumption in one line.
9. Portfolio questions ("I have these TINs", "my MLR", "what if I add…", "which TINs keep me under X%") go through \
portfolio_metrics and portfolio_suggest, which do the math exactly the way the workbook does. Never average per-TIN \
MLRs or PBPMs. The working portfolio is saved per chat and shown below when one exists; refer to it as "your \
portfolio" and update it when the user changes their list. For these users (actuaries, CFO/CEO/CSO) lead with the \
combined MLR, benchmark $, margin $ and person-years, state the target and whether it is met, and put per-TIN detail \
in a table. Say when a figure is an approximation (mixed spending classes, TINs sharing an NPI). Use the numbers the \
portfolio tools return — including their per-TIN table, cohort block and settlement lines — rather than recomputing \
them with run_sql or repeating the table with show_table; the tool keeps every figure on one consistent basis. \
That covers the combined maths only. To choose, screen or rank TINs on any other column (beneficiary counts, \
prevalence, per-TIN settlement, claims, data-quality notes…), use run_sql freely, then hand the resulting TINs to \
the portfolio tools: as tins to portfolio_metrics for their combined figures or a what-if, or as candidate_tins to \
portfolio_suggest for additions against a target. If a screen returns more TINs than a query result can list, \
tighten or rank it and say which cut you applied. \
The portfolio tools already show the user a per-TIN table with a TOTAL row, so do not repeat the per-TIN rows or \
the combined figures a second time in your text: give the answer and the target gap first, then only what the table \
does not show (settlement lines, cohorts, caveats). The same holds for the candidates table that portfolio_suggest \
shows: do not list those candidates again in a table of your own; give the add or remove plan in a small table, and \
at most name two or three other candidates in a sentence, pointing to the table above for the rest. Describe cohorts by their numbers, not by judgement: say which \
cohort contributes the largest dollar shortfall to the target (its negative room_under_target_usd) rather than \
calling it "the problem". Describe model parameters as what these projections apply, using the values the tool returns (LEAD: \
benchmark_discount_rates_applied — "all five TIN projections apply a 3% benchmark discount"); never write that a \
classification means a rule applies. The settlement figure applies the sharing rules to the pooled margin as one ACO: \
say "pooled" when you report it and that pooling is a modeling assumption, and when \
sum_of_standalone_tin_results_usd differs materially mention that summing the TINs' standalone results gives that \
other figure. Whenever you compare the two, give the reason in pooled_vs_standalone_note and no other. Label the \
settlement lines with the wording in settlement_line_labels. When the per-TIN table carries a standalone projected \
net settlement column, say in one line how many TINs are projected to receive money and how many to owe it. State \
the overlap caveat as population_overlap_note words it. In a stress test, the PCC repayment, guarantee and withhold stay \
at base case; say so. TINs returned by portfolio_suggest are mathematical candidates: name the objective (fewest \
additions, largest by benchmark…) and say that operational eligibility and beneficiary overlap have not been checked. \
Suggestions never change the saved portfolio; only an explicit instruction from the user does. A stress test or \
what-if applies only to the question that asked for it: later questions go back to the base case, and you do not \
re-run or extend an earlier scenario (for example on a new set of TINs) unless the user asks.
10. What-if on a model parameter (a different discount, sharing rate, withhold, cap…). Answer it as a limited \
sensitivity when the workbook's own formula for that parameter and every input it needs are in the data: compute it \
with SQL at full precision, and show the benchmark, expense and savings of the base case and of the scenario to the cent (two decimals) in one table, never each rounded on its own to whole dollars or millions (independently rounded figures can be a dollar out against each other; a shorter figure in the opening sentence is fine), so that they \
reconcile as displayed. Say which population it covers (the saved portfolio if there is one, otherwise the rows the \
parameter applies to, with their count), what you changed and what you held fixed, and that it is a sensitivity on \
that one parameter, not a re-run of the model. Recalculate only the downstream measures the data supports, name \
the settlement components you did not recalculate, and do not present a partial calculation as the projected net \
settlement. A what-if never changes the saved portfolio or the base case. When the formula or its dependencies are \
not in the data (a different risk-adjustment model, re-run alignment, a changed trend assumption whose inputs are not \
all present), explain what is missing instead of constructing a calculation.
11. Business language. The readers are executives, not developers. Never mention tool names, field names or the \
words "the tool" or any paraphrase of it ("the suggestion tool", "the screen I ran", "my query") — no \
portfolio_metrics, run_sql or "via …" in the answer or the "Based on" line, which lists workbook column \
names only. State a limit as a fact about the analysis ("candidates were screened on the base case"), not about tooling. Say "spending reduction needed to reach the \
target" for a shortfall, "room under the target" for a surplus, and "contribution to the target gap" for a TIN's or \
cohort's share. Keep the measures apart and label each: gross savings (before sharing), shared savings (after \
corridors/sharing; where sequestration applies it is its own line and the result is "shared savings net of \
sequestration") and projected net settlement (after repayments).
12. Corrections. Results from earlier turns may be shown to you shortened to save space; the full result was in front \
of you when you wrote that earlier answer. Never retract or cast doubt on an earlier statement because its \
supporting detail is no longer visible. If you need to re-check a TIN or figure, query that specific TIN first; \
correct only what the query shows to be wrong, and say "not re-verified" rather than "incorrect" for anything you \
did not re-check. A TIN missing from a top-N list is not missing from the data.
12. Precision of claims. (a) Any count you state against a threshold ("two are at or below 90%", "five exceed \
100%") must come from a query on the unrounded values, never from reading rounded figures in a table. The same goes \
for vague quantifiers: do not write "several", "most" or "a few" about rows against a threshold — count them in the \
query and give the number ("all 20 are above 85%"). (b) Answer the \
question that was asked; do not volunteer conclusions about relationships, causes or data quality. Comparing a top-N \
group with everyone else shows nothing about a relationship; if the user asks for one, analyse it across all eligible \
rows. When you do compare a subset with "the rest", exclude the subset from the rest and label both. (c) When a word \
in the question fits more than one column and the choice changes the result (e.g. "beneficiaries": the PY2027 count \
vs the 2026 base-year count), state the basis you used and say in one line that the other basis gives a different \
list. Do this only when that column is actually used to filter or rank the result; if it is merely displayed, or not \
used at all, say nothing about alternative bases. (d) When rows drop out for missing data, report how many within the \
filtered population, not the whole table. (e) Tables (show_table and ranking tables): show the identifier, name, the \
filter column, the ranked measure and the measures asked for, with units and years in the headers; leave other \
columns out unless asked (no NPI, beneficiary counts or duplicate measures the user did not request). Return MLRs and \
other ratios as percentages in the SQL — round(100 * expense / benchmark, 2) AS "MLR %" — never as fractions like \
0.8735, in tables and charts alike.
13. SQL dialect is DuckDB: quantile_cont(x, 0.5), median(x), ILIKE, TRY_CAST, round(x, 2), FILTER (WHERE …), \
QUALIFY, GROUP BY ALL. Only SELECT statements are allowed.

# Data
{schema}
{context}"""


def make_client():
    """Claude API or Claude in Microsoft Foundry, chosen by CLAUDE_PROVIDER."""
    if config.CLAUDE_PROVIDER == "foundry":
        from anthropic import AsyncAnthropicFoundry
        kw: dict = {}
        if config.FOUNDRY_BASE_URL:
            kw["base_url"] = config.FOUNDRY_BASE_URL
        elif config.FOUNDRY_RESOURCE:
            kw["resource"] = config.FOUNDRY_RESOURCE
        else:
            raise RuntimeError("CLAUDE_PROVIDER=foundry needs ANTHROPIC_FOUNDRY_RESOURCE or ANTHROPIC_FOUNDRY_BASE_URL")
        if config.FOUNDRY_USE_ENTRA_ID:
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("FOUNDRY_USE_ENTRA_ID=true needs the azure-identity package (pip install azure-identity)") from e
            sync_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")

            async def token_provider() -> str:            # tokens are cached by azure-identity; refresh is automatic
                return await asyncio.to_thread(sync_provider)
            kw["azure_ad_token_provider"] = token_provider
        else:
            if not config.FOUNDRY_API_KEY:
                raise RuntimeError("CLAUDE_PROVIDER=foundry needs ANTHROPIC_FOUNDRY_API_KEY (or FOUNDRY_USE_ENTRA_ID=true)")
            kw["api_key"] = config.FOUNDRY_API_KEY
        log.info("Claude provider: Microsoft Foundry (%s), deployment %s, auth %s",
                 config.FOUNDRY_BASE_URL or config.FOUNDRY_RESOURCE, config.ANTHROPIC_MODEL,
                 "Entra ID" if config.FOUNDRY_USE_ENTRA_ID else "API key")
        # The SDK also reads ANTHROPIC_FOUNDRY_RESOURCE / _BASE_URL from the environment and refuses both at once,
        # so hide the one we are not using while the client is built.
        hidden = {k: os.environ.pop(k) for k in ("ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_BASE_URL") if k in os.environ}
        try:
            return AsyncAnthropicFoundry(**kw)
        finally:
            os.environ.update(hidden)
    log.info("Claude provider: Claude API, model %s", config.ANTHROPIC_MODEL)
    return AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY or None)


class Agent:
    def __init__(self, warehouse: Warehouse):
        self.wh = warehouse
        self.client = make_client()
        self.programs = warehouse.programs                     # id -> info
        self.calcs, self.calc_errors = make_calcs(warehouse)
        shared = _read_text(config.DATA_DIR / "context.md")
        self.system_texts: dict[str, str] = {}
        for pid, info in self.programs.items():
            specific = _read_text(config.DATA_DIR / f"context-{pid.lower()}.md")
            others = [f"{o['label']} ({oid})" for oid, o in self.programs.items() if oid != pid]
            intro = (f"This chat is scoped to the **{info['label']}** dataset ({info['description']}). "
                     + (f"Other datasets in this app: {', '.join(others)}. Queries here can only read this chat's "
                        f"dataset: when a question is about a figure or concept that exists only in another one, say "
                        f"which dataset holds it and that the user needs to start a new chat on that dataset — do not "
                        f"offer to run it here. For a side-by-side view of the same TINs use compare_programs."
                        if others else ""))
            context = ""
            if shared:
                context += f"\n# Shared notes about these workbooks\n{shared}\n"
            if specific:
                context += f"\n# Domain reference: {info['label']}\n{specific}\n"
            self.system_texts[pid] = SYSTEM_TEMPLATE.format(
                app_name=config.APP_NAME, program_intro=intro,
                schema=warehouse.schema_summary(pid), context=context)
        self.default_program = next(iter(self.programs)) if len(self.programs) == 1 else None

    def tools_for(self, program: str) -> list[dict]:
        tools = list(TOOLS)
        if len(self.calcs) > 1:
            tools.append(COMPARE_TOOL)
        return tools

    # ---------------------------------------------------------------- tools
    def _run_tool(self, name: str, args: dict, state: dict, history: list | None = None) -> tuple[str, dict]:
        """Execute a tool. Returns (text result for Claude, UI block for the browser). May update state."""
        program = state.get("program") or self.default_program
        if name == "recall_result":
            rid = str(args.get("result_id", "")).strip()
            found = find_result(history or [], state, rid)
            block = {"type": "tool", "name": name, "label": "Checked an earlier result", "ok": found is not None}
            if found is None:
                block["detail"] = "not stored any more"
                return json.dumps({"error": f"No stored result with id {rid!r}. It is no longer kept; run the "
                                            "query or calculation again to get it."}), block
            return found, block
        if name == "search_columns":
            res = self.wh.search_columns(args.get("keywords", ""), args.get("table"), program=program)
            n = len(res.get("matches", []))
            return json.dumps(res, default=str), {
                "type": "tool", "name": name, "label": f"Searched columns: {args.get('keywords', '')}",
                "detail": f"{n} match{'es' if n != 1 else ''}", "ok": "error" not in res}

        if name == "run_sql":
            res = self.wh.query(args.get("sql", ""), config.MAX_ROWS_TO_CLAUDE, program=program,
                                max_chars=config.MAX_RESULT_CHARS_TO_CLAUDE)
            block = {"type": "tool", "name": name, "label": args.get("purpose") or "Ran a query",
                     "sql": args.get("sql", ""), "ok": "error" not in res}
            if "error" in res:
                block["detail"] = res["error"][:300]
            else:
                block["detail"] = f"{res['row_count']} row{'s' if res['row_count'] != 1 else ''}"
            return json.dumps(res, default=str), block

        if name == "show_table":
            res = self.wh.query(args.get("sql", ""), config.MAX_ROWS_TO_UI, program=program,
                                max_chars=config.MAX_RESULT_CHARS_TO_UI)
            if "error" in res:
                return json.dumps(res), {"type": "tool", "name": name, "label": args.get("title", "Table"),
                                         "sql": args.get("sql", ""), "ok": False, "detail": res["error"][:300]}
            preview = {"shown_to_user": True, "row_count": res["row_count"], "truncated": res["truncated"],
                       **_preview(res["columns"], res["rows"], 15, "first_rows")}
            return json.dumps(preview, default=str), {
                "type": "table", "title": args.get("title", ""), "sql": args.get("sql", ""),
                "columns": res["columns"], "rows": res["rows"], "truncated": res["truncated"]}

        if name == "create_chart":
            return self._chart(args, program)

        if name == "portfolio_metrics":
            return self._portfolio_metrics(args, state, program)

        if name == "portfolio_suggest":
            return self._portfolio_suggest(args, state, program)

        if name == "compare_programs":
            return self._compare(args, state)

        return json.dumps({"error": f"Unknown tool {name}"}), {"type": "tool", "name": name, "label": name, "ok": False}

    def _chart(self, a: dict, program: str | None = None) -> tuple[str, dict]:
        ctype = a.get("chart_type", "bar")
        limit = 20000 if ctype == "scatter" else 1000
        res = self.wh.query(a.get("sql", ""), limit, program=program, max_chars=config.MAX_RESULT_CHARS_TO_UI)
        fail = {"type": "tool", "name": "create_chart", "label": a.get("title", "Chart"),
                "sql": a.get("sql", ""), "ok": False}
        if "error" in res:
            fail["detail"] = res["error"][:300]
            return json.dumps(res), fail
        cols = res["columns"]
        x, ys = a.get("x"), a.get("y") or []
        missing = [c for c in [x, *ys, a.get("point_label")] if c and c not in cols]
        if missing:
            msg = {"error": f"Columns {missing} not in query result. Result columns: {cols}"}
            fail["detail"] = msg["error"][:300]
            return json.dumps(msg), fail
        if not res["rows"]:
            msg = {"error": "Query returned no rows; nothing to chart."}
            fail["detail"] = msg["error"]
            return json.dumps(msg), fail
        xi = cols.index(x)
        rows = res["rows"]
        if ctype == "scatter":
            li = cols.index(a["point_label"]) if a.get("point_label") else None
            datasets = [{"label": y, "data": [
                {"x": r[xi], "y": r[cols.index(y)], **({"label": r[li]} if li is not None else {})}
                for r in rows if r[xi] is not None and r[cols.index(y)] is not None]} for y in ys]
            labels = []
        else:
            labels = [("(blank)" if r[xi] is None else r[xi]) for r in rows]
            datasets = [{"label": y, "data": [r[cols.index(y)] for r in rows]} for y in ys]
        chart = {"type": "chart", "title": a.get("title", ""), "chart_type": ctype, "labels": labels,
                 "datasets": datasets, "x_label": a.get("x_label") or x,
                 "y_label": a.get("y_label") or (ys[0] if len(ys) == 1 else ""),
                 "value_format": a.get("value_format", "number"), "sql": a.get("sql", ""),
                 "truncated": res["truncated"],
                 # Charts saved before 2026.10.02-12 hold fractions under 'percent'; the browser tells them apart by this.
                 "percent_scale": "percent"}
        back = {"chart_shown_to_user": True, "points": len(rows), "truncated": res["truncated"],
                **_preview(cols, rows, 40, "rows")}
        return json.dumps(back, default=str), chart

    # ------------------------------------------------------------ portfolio
    def _no_calc(self, program: str | None) -> str:
        why = getattr(self, "calc_errors", {}).get(program or "", "its headline columns were not recognised")
        return f"Portfolio figures are not available for the {program} dataset: {why} Tell the user; do not work them out with run_sql."

    def _portfolio_metrics(self, a: dict, state: dict, program: str | None) -> tuple[str, dict]:
        calc = self.calcs.get(program or "")
        if not calc:
            return json.dumps({"error": self._no_calc(program)}), \
                {"type": "tool", "name": "portfolio_metrics", "label": "Portfolio", "ok": False}
        action = a.get("action") or "set"
        save = a.get("save", True)
        current = list(state.get("portfolio") or [])
        given = clean_tins(a.get("tins"))
        if action == "current":
            tins = current
        elif action == "add":
            tins = current + [t for t in given if t not in current]
        elif action == "remove":
            tins = [t for t in current if t not in set(given)]
        else:
            tins = given
        if not tins:
            msg = {"error": "No TINs to evaluate. Ask the user for their TIN list." if action == "current" else "No valid TINs given."}
            return json.dumps(msg), {"type": "tool", "name": "portfolio_metrics", "label": "Portfolio", "ok": False, "detail": msg["error"]}
        target = a.get("target_mlr") or state.get("target_mlr")
        shock_e, shock_b = float(a.get("expense_change_pct") or 0), float(a.get("benchmark_change_pct") or 0)
        res = calc.metrics(tins, target_mlr=target, expense_change_pct=shock_e, benchmark_change_pct=shock_b)
        if shock_e or shock_b:
            save = False
        if save and action != "current":
            state["portfolio"] = [t["tin"] for t in res["tins"]]
        if a.get("target_mlr") and save:   # a what-if (save=false) or stress test leaves the saved target alone
            state["target_mlr"] = a["target_mlr"]
        res["working_portfolio_saved"] = bool(save and action != "current")
        res.update(_tin_list("working_portfolio", state.get("portfolio", [])))
        c = res["combined"]
        pct = lambda v: round(v * 100, 2) if v is not None else None
        ck = calc._cls_key()
        cols = ["TIN", "Organization", calc.spec.cls_header, "Person years", "Benchmark $", "Expense $", "Gross margin $", "MLR %"]
        rows = [[t["tin"], t["organization"], t.get(ck, ""), t["person_years"], t["benchmark_usd"], t["expense_usd"],
                 t["gross_margin_usd"], pct(t["mlr"])] for t in res["tins"]]
        total = ["TOTAL", f"{res['tin_count']} TINs", "", c["person_years"], c["benchmark_usd"], c["expense_usd"],
                 c["gross_margin_usd"], pct(c["mlr"])]
        if "sum_of_tin_projected_net_settlement_usd" in c:   # each TIN's standalone workbook figure; base case only
            cols.append("Projected net settlement $ (standalone)")
            for row, t in zip(rows, res["tins"]):
                row.append(t.get("projected_net_settlement_usd"))
            total.append(c["sum_of_tin_projected_net_settlement_usd"])
        shown = rows[:config.MAX_ROWS_TO_UI]
        rows = shown + [total]
        label = {"set": "Portfolio", "add": "Portfolio after adding", "remove": "Portfolio after removing", "current": "Current portfolio"}[action]
        title = f"{program} {label.lower()}: {res['tin_count']} TINs · MLR {c['mlr']:.1%}" if c["mlr"] is not None else label
        if shock_e or shock_b:
            parts = [f"expense {shock_e:+g}%" if shock_e else "", f"benchmark {shock_b:+g}%" if shock_b else ""]
            title = f"Stress test ({', '.join(p for p in parts if p)}) · " + title
        elif not save:
            title = "What-if · " + title
        sub = (f"Benchmark ${c['benchmark_usd']/1e6:,.1f}M · expense ${c['expense_usd']/1e6:,.1f}M · "
               f"margin ${c['gross_margin_usd']/1e6:,.1f}M · {c['person_years']:,.0f} person-years")
        if res.get("target"):
            sub += f" · {'meets' if res['target']['meets_target'] else 'misses'} {res['target']['target_mlr']:.0%} target"
        block = {"type": "table", "title": title, "sql": "", "columns": cols, "rows": rows,
                 "truncated": len(shown) < res["tin_count"], "subtitle": sub}
        if res["tin_count"] > config.MAX_TINS_TO_CLAUDE:   # totals and cohorts above still cover every TIN
            res["tins"] = sorted(res["tins"], key=lambda t: -t["benchmark_usd"])[:config.MAX_TINS_TO_CLAUDE]
            res["tins_note"] = (f"Only the {config.MAX_TINS_TO_CLAUDE} largest of {res['tin_count']} TINs by benchmark are "
                                f"listed here. The combined figures, cohorts and target cover all {res['tin_count']}, and "
                                f"the user's table lists them.")
        return json.dumps(res, default=str), block

    def _portfolio_suggest(self, a: dict, state: dict, program: str | None) -> tuple[str, dict]:
        calc = self.calcs.get(program or "")
        if not calc:
            return json.dumps({"error": self._no_calc(program)}), \
                {"type": "tool", "name": "portfolio_suggest", "label": "Suggest TINs", "ok": False}
        tins = clean_tins(a.get("tins")) or list(state.get("portfolio") or [])
        target = float(a.get("target_mlr"))
        state["target_mlr"] = target
        limit = max(1, min(int(a.get("limit") or 25), 100))
        res = calc.suggest(tins, target, exclude=clean_tins(a.get("exclude_tins")), name_like=a.get("name_like"),
                           class_like=a.get("spending_class"), min_person_years=a.get("min_person_years"),
                           max_person_years=a.get("max_person_years"), limit=limit,
                           candidates=clean_tins(a.get("candidate_tins")))
        res.update(_tin_list("working_portfolio", tins))
        ck = calc._cls_key()
        cols = ["TIN", "Organization", calc.spec.cls_header, "Person years", "Benchmark $", "Gross margin $", "MLR %", "Room under target $"]
        cand = res["candidates"]["largest_by_benchmark"]
        rows = [[t["tin"], t["organization"], t.get(ck, ""), t["person_years"], t["benchmark_usd"], t["gross_margin_usd"],
                 round(t["mlr"] * 100, 2), t["room_under_target_usd"]] for t in cand]
        cur = res["current"]
        status = "meets" if cur["meets_target"] else "does not meet"
        title = (f"Candidates with MLR ≤ {target:.0%} (largest {len(cand)} of {res['candidates']['with_mlr_at_or_below_target']:,} by benchmark)"
                 if tins else f"TINs with MLR ≤ {target:.0%} (largest {len(cand)} of {res['candidates']['with_mlr_at_or_below_target']:,})")
        block = {"type": "table", "title": title, "sql": "", "columns": cols, "rows": rows, "truncated": False,
                 "subtitle": f"Portfolio of {cur['tin_count']} TINs {status} the {target:.0%} target (MLR {cur['mlr']:.1%})" if cur["mlr"] else ""}
        res["table_shown_to_user"] = (
            f"The user sees ONE table from this result: candidates.largest_by_benchmark, {len(cand)} of the "
            f"{res['candidates']['with_mlr_at_or_below_target']:,} candidates at or below the target, in that order "
            "(row 1 = largest benchmark). It is not the full list and it is not ranked by margin. Nothing else here is "
            "shown to them: not largest_by_margin, not the add or remove plan. When you name a TIN that is not in that "
            "table, say so; when asked about a position in 'the table', answer from largest_by_benchmark.")
        return json.dumps(res, default=str), block

    def _compare(self, a: dict, state: dict) -> tuple[str, dict]:
        tins = clean_tins(a.get("tins")) or list(state.get("portfolio") or [])
        if not tins:
            return json.dumps({"error": "No TINs given and no working portfolio."}), \
                {"type": "tool", "name": "compare_programs", "label": "Compare programs", "ok": False}
        res = compare_programs(self.calcs, tins)
        pids = list(res["programs"])
        cols = ["Measure"] + pids
        def row(label, key, fmt=lambda v: v):
            return [label] + [fmt(res["programs"][p].get(key)) for p in pids]
        pct = lambda v: round(v * 100, 2) if isinstance(v, (int, float)) else v
        rows = [row("TINs found", "tins_found"), row("Person-years", "person_years"), row("Benchmark $", "benchmark_usd"),
                row("Expense $", "expense_usd"), row("Gross margin $", "gross_margin_usd"), row("MLR %", "mlr", pct),
                row("Shared result $", "shared_result_usd")]
        block = {"type": "table", "title": f"Program comparison · {len(tins)} TINs", "sql": "", "columns": cols, "rows": rows,
                 "truncated": False, "subtitle": " · ".join(res['programs'][p]['shared_result_basis'] for p in pids)}
        res.update(_tin_list("tins_requested", res["tins_requested"]))
        if len(res["per_tin"]) > config.MAX_TINS_TO_CLAUDE:
            res["per_tin_note"] = (f"Only the first {config.MAX_TINS_TO_CLAUDE} of {len(res['per_tin'])} TINs are listed; "
                                   f"the program totals cover all of them.")
            res["per_tin"] = res["per_tin"][:config.MAX_TINS_TO_CLAUDE]
        return json.dumps(res, default=str), block

    # ----------------------------------------------------------------- loop
    async def run(self, history: list, user_text: str, state: dict | None = None,
                  effort: str | None = None) -> AsyncIterator[dict]:
        """Append the user's turn to `history` (mutated in place) and stream UI events.
        `state` is the conversation's working set (portfolio TINs, target); tools may update it.
        `effort` is the reasoning depth for this question; None = the configured default."""
        state = state if state is not None else {}
        summary_usage = await self._compact_if_needed(history, state)
        if summary_usage:
            yield summary_usage
        history.append({"role": "user", "content": [{"type": "text", "text": user_text}]})
        extra = {"extra_headers": {"anthropic-beta": config.ANTHROPIC_BETAS}} if config.ANTHROPIC_BETAS else {}
        effort = effort if effort in config.EFFORT_LEVELS else config.ANTHROPIC_EFFORT
        if effort:
            extra["output_config"] = {"effort": effort}
        # Static block first (cached), then the small dynamic block. Prefix caching keeps the big block warm.
        # Both are fixed for the whole question: the model's reasoning blocks are only valid while what came
        # before them is unchanged, and a tool that changes the portfolio says so in its own result.
        program = state.get("program") or self.default_program or next(iter(self.system_texts))
        system = [{"type": "text", "text": self.system_texts[program], "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": _dynamic_text(state)}]

        for round_no in range(config.MAX_TOOL_ROUNDS + 1):
            last_round = round_no == config.MAX_TOOL_ROUNDS
            kwargs = dict(model=config.ANTHROPIC_MODEL, max_tokens=config.MAX_TOKENS, system=system,
                          tools=self.tools_for(program), messages=_prepare(history), **extra)
            if last_round:
                kwargs["tool_choice"] = {"type": "none"}
            for attempt in (1, 2):
                try:
                    async with self.client.messages.stream(**kwargs) as stream:
                        async for event in stream:
                            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                                yield {"type": "text", "text": event.delta.text}
                            elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                                yield {"type": "tool_pending", "name": event.content_block.name}
                        final = await stream.get_final_message()
                    break
                except BadRequestError as e:
                    # A reasoning block the service will not take back: answer this round without them, once.
                    if attempt == 2 or "thinking" not in str(e).lower() or not strip_thinking(history):
                        raise
                    log.warning("Reasoning blocks rejected (%s); retrying without them", str(e)[:200])
                    kwargs["messages"] = _prepare(history)
            yield _usage_event(final, config.ANTHROPIC_MODEL, "chat")

            # Reasoning blocks go back unchanged with the tool results, so the model keeps its line of thought
            # from one tool call to the next; they are dropped once the question is answered.
            content = []
            for b in final.content:
                if b.type == "text":
                    content.append({"type": "text", "text": b.text})
                elif b.type == "tool_use":
                    content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                elif b.type == "thinking":
                    content.append({"type": "thinking", "thinking": b.thinking, "signature": b.signature})
                elif b.type == "redacted_thinking":
                    content.append({"type": "redacted_thinking", "data": b.data})
            if not any(c["type"] in ("text", "tool_use") for c in content):
                content.append({"type": "text", "text": "(no response)"})
            history.append({"role": "assistant", "content": content})

            if final.stop_reason == "max_tokens":
                yield {"type": "text", "text": "\n\n*(Response cut off — ask me to continue.)*"}
            if final.stop_reason != "tool_use":
                break

            results = []
            for b in content:
                if b["type"] != "tool_use":
                    continue
                try:
                    text, block = await asyncio.to_thread(self._run_tool, b["name"], b["input"], state, history)
                except Exception as e:  # never let a tool crash the chat
                    log.exception("tool failed")
                    text = json.dumps({"error": str(e)[:500]})
                    block = {"type": "tool", "name": b["name"], "label": b["name"], "ok": False, "detail": str(e)[:300]}
                yield {"type": "block", "block": block}
                text = within_budget(text)
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": text,
                                **({"is_error": True} if '"error"' in text[:20] else {})})
            history.append({"role": "user", "content": results})
        strip_thinking(history)

    # ------------------------------------------------------------ compaction
    async def _compact_if_needed(self, history: list, state: dict | None = None) -> dict | None:
        """Keep long chats within budget: summarize the older part of the transcript once it grows past
        COMPACT_AFTER_TOKENS (estimated). The summary replaces those turns in the stored history; the working
        portfolio lives in state, so nothing the user relies on depends on the transcript alone."""
        if _estimate_tokens(history) <= config.COMPACT_AFTER_TOKENS:
            return None
        # Keep the most recent complete exchanges verbatim.
        cut = _turn_starts(history)
        if len(cut) <= config.COMPACT_KEEP_TURNS + 1:
            return None
        split = cut[-config.COMPACT_KEEP_TURNS]
        old, recent = history[:split], history[split:]
        transcript = _transcript(old)[-300_000:]
        try:
            resp = await self.client.messages.create(
                model=config.SUMMARY_MODEL or config.ANTHROPIC_MODEL, max_tokens=2500,
                system="You summarize an analytics chat so it can continue without the original transcript.",
                messages=[{"role": "user", "content":
                    "Summarize this conversation between a user and a data assistant. Keep: the user's goals and "
                    "definitions, every TIN list, target or assumption they stated, the key numbers found (with the "
                    "column names used), decisions and open questions. Be compact; use bullet points.\n\n" + transcript}],
            )
            summary = "".join(b.text for b in resp.content if b.type == "text").strip()
        except Exception:
            log.exception("compaction failed; continuing with full history")
            return None
        kept = archive_results(old, state) if state is not None else []
        if kept:
            summary += ("\n\nEarlier results that can still be read in full with recall_result (id — what it was):\n"
                        + "\n".join(f"- {r['id']} — {r['tool']}({json.dumps(r['input'], default=str)[:300]})" for r in kept))
        history[:] = [
            {"role": "user", "content": [{"type": "text", "text": "[Summary of the earlier part of this chat]\n" + summary}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Understood. I'll continue from that summary."}]},
            *recent,
        ]
        log.info("Compacted conversation: %d older messages summarized", len(old))
        return _usage_event(resp, config.SUMMARY_MODEL or config.ANTHROPIC_MODEL, "summary")


def make_calcs(wh: Warehouse) -> tuple[dict[str, PortfolioCalc], dict[str, str]]:
    """A portfolio calculator per program, and for programs without one the reason shown to the user."""
    calcs: dict[str, PortfolioCalc] = {}
    errors: dict[str, str] = {}
    for pid in wh.programs:
        try:
            spec = build_spec(wh, pid)
        except PortfolioUnavailable as e:
            errors[pid] = str(e)
            log.error("Portfolio tools disabled for %s: %s", pid, e)
            continue
        if spec:
            calcs[pid] = PortfolioCalc(wh, spec)
        else:
            errors[pid] = "its headline columns were not recognised."
            log.warning("Portfolio tools disabled for %s: no recognised headline columns", pid)
    return calcs, errors


def within_budget(text: str, budget: int | None = None) -> str:
    """The last guard on what any tool sends to Claude. Each tool sizes its own lists; this bounds the whole
    serialized result, so a field nobody thought to cap (a long warning, a new list) cannot overflow the
    context. Long lists and strings are cut progressively, with a marker saying how much was left out."""
    budget = budget or config.MAX_RESULT_CHARS_TO_CLAUDE
    if len(text) <= budget:
        return text
    try:
        obj = json.loads(text)
    except ValueError:
        return text[:budget] + " …[cut to the size limit]"
    for items, chars in ((200, 4000), (100, 2000), (50, 1000), (25, 500), (10, 300), (5, 200)):
        out = json.dumps(_shrink(obj, items, chars), default=str)
        if len(out) <= budget:
            return out
    return json.dumps({"error": "The result was too large to return even after shortening. Ask for less at once: "
                                "fewer TINs, fewer columns, or an aggregate."})


def _shrink(x, items: int, chars: int):
    if isinstance(x, dict):
        return {k: _shrink(v, items, chars) for k, v in x.items()}
    if isinstance(x, list):
        out = [_shrink(v, items, chars) for v in x[:items]]
        return out + [f"… {len(x) - items} more not shown"] if len(x) > items else out
    if isinstance(x, str) and len(x) > chars:
        return x[:chars] + f"… [{len(x) - chars} more characters not shown]"
    return x


def _usage_event(message, model: str, kind: str) -> dict:
    """Token counts from an API response, as a stream event the server records."""
    u = getattr(message, "usage", None)
    g = lambda name: int(getattr(u, name, 0) or 0) if u is not None else 0
    return {"type": "usage", "model": model, "kind": kind, "input": g("input_tokens"), "output": g("output_tokens"),
            "cache_write": g("cache_creation_input_tokens"), "cache_read": g("cache_read_input_tokens")}


def _read_text(path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _preview(cols: list, rows: list, n: int, key: str, max_cols: int = 60) -> dict:
    """The first rows of something the user was shown in full, sized for Claude: at most max_cols columns and
    as many of the first n rows as fit in the result size cap."""
    out = {"columns": cols[:max_cols]}
    if len(cols) > max_cols:
        out["columns_note"] = f"First {max_cols} of {len(cols)} columns; the user sees all of them."
    out[key] = fit_rows([r[:max_cols] for r in rows[:n]], config.MAX_RESULT_CHARS_TO_CLAUDE // 2)
    return out


def _tin_list(key: str, tins: list[str], shown: int = 300) -> dict:
    """A TIN list for a tool result: the list itself, or its count and the first `shown` when it is long."""
    if len(tins) <= shown:
        return {key: tins}
    return {key: tins[:shown], f"{key}_count": len(tins), f"{key}_note": f"First {shown} of {len(tins)} TINs listed."}


def _dynamic_text(state: dict) -> str:
    """The part of the system prompt that changes between calls; kept after the cached block."""
    today = f"Today is {dt.date.today().isoformat()}."
    tins = state.get("portfolio") or []
    if not tins:
        return today
    lines = [today, f"# Working portfolio for this chat ({len(tins)} TINs, saved by portfolio_metrics; dataset {state.get('program', '')})",
             ", ".join(tins[:300]) + (" …" if len(tins) > 300 else "")]
    if state.get("target_mlr"):
        lines.append(f"Target MLR: {state['target_mlr']:.2%}")
    lines.append("Use portfolio_metrics(action='current') to get its numbers; call it again with 'add'/'remove' when the user changes the list.")
    return "\n".join(lines)


def _estimate_tokens(history: list) -> int:
    return len(json.dumps(history)) // 4


def _turn_starts(history: list) -> list[int]:
    """Indexes where a user *text* message starts a new exchange."""
    return [i for i, m in enumerate(history) if m["role"] == "user" and any(c.get("type") == "text" for c in m["content"])]


def _transcript(msgs: list) -> str:
    out = []
    for m in msgs:
        for c in m["content"]:
            if c.get("type") == "text":
                out.append(f"{m['role'].upper()}: {c['text']}")
            elif c.get("type") == "tool_use":
                out.append(f"ASSISTANT called {c['name']}({json.dumps(c['input'])[:600]})")
            elif c.get("type") == "tool_result":
                body = c.get("content") if isinstance(c.get("content"), str) else json.dumps(c.get("content"))
                out.append(f"RESULT: {body[:800]}")
    return "\n".join(out)


def _prepare(history: list) -> list:
    """Copy history for the API: shrink old tool results and add a cache breakpoint."""
    msgs = copy.deepcopy(history)
    starts = _turn_starts(msgs)
    for m in msgs[:starts[-1]] if starts else []:   # reasoning blocks are only replayed within the current question
        m["content"] = [c for c in m["content"] if c.get("type") not in THINKING_TYPES] or m["content"]
    # Keep full tool output for the current and the previous exchange (follow-ups such as "add those two" or
    # "go back to the original five" lean on the previous answer's evidence); older results get trimmed.
    keep_from = starts[-2] if len(starts) >= 2 else 0
    for m in msgs[:keep_from]:
        for c in m["content"]:
            if c.get("type") == "tool_result" and isinstance(c.get("content"), str) and len(c["content"]) > 1500:
                c["content"] = c["content"][:1500] + (
                    " …[shortened to save space; the full result was available when the answer that followed was "
                    f"written. Result id: {c.get('tool_use_id', '')} — call recall_result with this id to read it in "
                    "full before relying on anything not shown here]")
    if msgs and msgs[-1]["content"]:
        msgs[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return msgs


THINKING_TYPES = ("thinking", "redacted_thinking")


def strip_thinking(history: list) -> bool:
    """Remove the model's reasoning blocks from a stored history (in place). True if any were removed."""
    removed = False
    for m in history:
        if m["role"] == "assistant" and any(c.get("type") in THINKING_TYPES for c in m["content"]):
            m["content"] = [c for c in m["content"] if c.get("type") not in THINKING_TYPES] or \
                [{"type": "text", "text": "(no response)"}]
            removed = True
    return removed


def find_result(history: list, state: dict, result_id: str) -> str | None:
    """The full text of an earlier tool result: from the transcript, else from the archive kept at compaction."""
    if not result_id:
        return None
    for m in history:
        for c in m["content"]:
            if c.get("type") == "tool_result" and c.get("tool_use_id") == result_id:
                return c["content"] if isinstance(c.get("content"), str) else json.dumps(c.get("content"), default=str)
    for r in state.get(ARCHIVE_KEY) or []:
        if r["id"] == result_id:
            return r["result"]
    return None


ARCHIVE_KEY = "_result_archive"   # keys starting with "_" stay on the server (see public_state)


def archive_results(old: list, state: dict) -> list[dict]:
    """Before older turns are replaced by a summary, keep their tool results (newest first, within
    RESULT_ARCHIVE_CHARS) so recall_result still finds them. Returns the entries kept from `old`."""
    calls = {c["id"]: c for m in old for c in m["content"] if c.get("type") == "tool_use"}
    new = []
    for m in old:
        for c in m["content"]:
            call = calls.get(c.get("tool_use_id")) if c.get("type") == "tool_result" else None
            if call and isinstance(c.get("content"), str) and not c.get("is_error") and call["name"] != "recall_result":
                new.append({"id": call["id"], "tool": call["name"], "input": call["input"], "result": c["content"]})
    kept, used = [], 0
    for r in reversed((state.get(ARCHIVE_KEY) or []) + new):
        used += len(r["result"])
        if used > config.RESULT_ARCHIVE_CHARS:
            break
        kept.append(r)
    kept.reverse()
    state[ARCHIVE_KEY] = kept
    ids = {r["id"] for r in kept}
    return [r for r in new if r["id"] in ids]


def public_state(state: dict) -> dict:
    """The part of a chat's state the browser may see."""
    return {k: v for k, v in state.items() if not k.startswith("_")}


def repair_history(history: list) -> list:
    """Make a history valid after an interrupted turn (e.g. browser closed mid-answer)."""
    h = list(history)
    # Drop a trailing assistant tool_use without results, and any dangling user turn.
    while h:
        last = h[-1]
        if last["role"] == "assistant" and any(c.get("type") == "tool_use" for c in last["content"]):
            h.pop()
            continue
        if last["role"] == "user":
            h.pop()
            continue
        break
    return h
