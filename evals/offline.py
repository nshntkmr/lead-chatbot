"""Deterministic checks: no model calls, no cost. Portfolio math against the golden values in TESTING.md, and
the guard rails (result size caps, dataset scoping, blank-expense handling, what-if state)."""
from __future__ import annotations

import json

import duckdb

from app import config
from app.agent import Agent, make_calcs
from app.data import Warehouse
from app.portfolio import LeadSpec, PortfolioCalc, build_spec

LEAD_FIVE = ["10198331", "10211494", "10211501", "10211534", "10211551"]
MSSP_THREE = ["941156581", "363738206", "340714585"]


def bare_agent(wh: Warehouse) -> Agent:
    """An Agent with its tools but no API client."""
    agent = Agent.__new__(Agent)
    agent.wh, agent.programs, agent.default_program = wh, wh.programs, None
    agent.calcs, agent.calc_errors = make_calcs(wh)
    return agent


def run(wh: Warehouse) -> list[tuple[str, bool, str]]:
    """Returns (check, passed, detail) rows."""
    out: list[tuple[str, bool, str]] = []

    def check(name: str, got, want, tol: float = 0.0) -> None:
        ok = abs(got - want) <= tol if isinstance(want, (int, float)) and not isinstance(want, bool) else got == want
        out.append((name, ok, f"got {got!r}, expected {want!r}" + (f" ±{tol:g}" if tol else "")))

    agent = bare_agent(wh)
    lead, mssp = agent.calcs.get("LEAD"), agent.calcs.get("MSSP")

    if lead:
        m = lead.metrics(LEAD_FIVE, target_mlr=0.85)
        c = m["combined"]
        check("A4 LEAD combined MLR", c["mlr"], 0.9727, 0.00005)
        check("A4 LEAD benchmark $", c["benchmark_usd"], 174_608_462, 1)
        check("A4 LEAD margin $", c["gross_margin_usd"], 4_765_803, 1)
        check("A4 LEAD person-years", c["person_years"], 10_043.5, 0.05)
        check("A4 LEAD net shared savings $", c["net_shared_savings_usd"], 4_670_487, 1)
        check("A4 LEAD total monies owed $M", round(c["total_monies_owed_usd"] / 1e6, 2), -2.23, 0.005)
        check("A4 LEAD financial guarantee $M", round(c["financial_guarantee_usd"] / 1e6, 2), 6.32, 0.005)
        check("A4 LEAD standalone results summed unrounded", c["sum_of_standalone_tin_results_usd"], 4_670_487)
        check("A4 LEAD pooled = standalone explained by the first corridor",
              "first corridor" in c["pooled_vs_standalone_note"] and "agree" in c["pooled_vs_standalone_note"], True)
        by_tin = {t["tin"]: t.get("projected_net_settlement_usd") for t in m["tins"]}
        check("A4 LEAD per-TIN projected net settlement $", (by_tin["10211534"], by_tin["10211494"]), (978_948, -1_482_256))
        check("A4 LEAD per-TIN settlements sum $", c["sum_of_tin_projected_net_settlement_usd"], -2_234_141, 1)
        check("A4 LEAD settlement split 2 paid / 3 owed",
              "2 TIN(s) positive" in c["projected_net_settlement_by_tin_note"]
              and "3 negative" in c["projected_net_settlement_by_tin_note"], True)
        note = m.get("population_overlap_note", "")
        check("A4 LEAD overlap caveat: other keys absent, overlap not established",
              all(x in note for x in ("200050", "none of them is a TIN row", "distinct NPIs", "does not establish")), True)
        check("A4 LEAD net shared savings labelled net of sequestration",
              c["settlement_line_labels"]["net_shared_savings_usd"], "Shared savings net of sequestration")
        check("A4 LEAD shortfall to 85% $M", round(m["target"]["room_under_target_usd"] / 1e6, 1), -21.4, 0.05)
        cohorts = {x["cohort"]: x for x in m["cohorts"]}
        for k, want in (("Aged & Disabled", 91.6), ("High Needs", 101.7), ("ESRD", 106.6)):
            check(f"A4 LEAD cohort MLR % — {k}", cohorts[k]["mlr"] * 100, want, 0.06)
        check("A4 LEAD cohort margins sum to the total", sum(x["gross_margin_usd"] for x in m["cohorts"]),
              c["gross_margin_usd"], 5)
        check("A4 LEAD cohort gaps sum to the portfolio's", sum(x["room_under_target_usd"] for x in m["cohorts"]),
              m["target"]["room_under_target_usd"], 5)
        # Settlement lines against the workbook's own columns, for every TIN, including those beyond the first corridor.
        t = lead.spec.table
        rows = wh.execute(f'SELECT "Total benchmark", "Gross margin / total savings before risk corridors", '
                          f'"Settlement | shared savings or losses", "Settlement | sequestration" FROM "{t}" '
                          f'WHERE "Total benchmark" > 0', [])[1]
        worst_shared = max(abs(lead.spec.share(g, b)["shared_savings_after_global_corridors_usd"] - sh) for b, g, sh, _ in rows)
        worst_net = max(abs(lead.spec.net(g, b) - (sh + sq)) for b, g, sh, sq in rows)
        check("LEAD corridors reproduce the workbook's shared savings for every TIN ($)", worst_shared, 0, 1)
        check("LEAD sequestration reproduces the workbook's for every TIN, beyond the first corridor too ($)", worst_net, 0, 1)
        s = lead.suggest(LEAD_FIVE, 0.85)
        plan = s["add_to_reach_target"]
        check("A5 LEAD removal impossible", s["remove_to_reach_target"]["possible"], False)
        check("A5 LEAD add plan", [t["tin"] for t in plan["tins"]], ["910214500", "271081647"])
        check("A5 LEAD MLR % after each addition", [round(t["combined_mlr_after_adding"] * 100, 1) for t in plan["tins"]],
              [86.2, 83.6])
        check("A5 LEAD candidates at or under 85%", s["candidates"]["with_mlr_at_or_below_target"], 834)
        pool = ["910214500", "271081647", "10211534", "000000000"]   # two real candidates, one already held, one unknown
        sp = lead.suggest(LEAD_FIVE, 0.85, candidates=pool)
        check("A5 LEAD supplied candidate pool: only those TINs screened", sp["candidates"]["screened"], 2)
        check("A5 LEAD supplied candidate pool: add plan stays inside it",
              {t["tin"] for t in sp["add_to_reach_target"]["tins"]} <= set(pool), True)
        check("A5 LEAD supplied candidate pool: pool note given", "limited to the 4 TINs supplied" in sp["candidates"]["pool_note"], True)
        check("A5 LEAD no pool: no pool note", "pool_note" in s["candidates"], False)
        check("A5 LEAD above target: candidates are not described as meeting it in any combination",
              "Do not say any combination" in s["candidates"]["note"], True)
        check("A5 LEAD at target: candidates can be added in any combination",
              "any combination without breaking it" in lead.suggest(LEAD_FIVE, 0.99)["candidates"]["note"], True)
        m7 = lead.metrics(LEAD_FIVE + ["910214500", "271081647"])["combined"]
        check("A6 LEAD 7-TIN MLR", round(m7["mlr"] * 100, 1), 83.6)
        check("A6 LEAD 7-TIN margin $M", round(m7["gross_margin_usd"] / 1e6, 1), 111.1)
        check("A6 LEAD 7-TIN pooled vs standalone: both the TINs' and the pool's corridor position are given",
              all(x in m7["pooled_vs_standalone_note"] for x in ("go beyond the first corridor", "16.4% of the pooled benchmark")), True)
        hot = lead.metrics(LEAD_FIVE, expense_change_pct=3)["combined"]
        check("A7 LEAD +3% expense MLR", round(hot["mlr"] * 100, 1), 100.2)
        check("A7 LEAD +3% expense margin $k", round(hot["gross_margin_usd"] / 1e3), -329, 1)
        check("A7 LEAD +3% expense net shared $k", round(hot["net_shared_savings_usd"] / 1e3), -336, 1)
        delta = lead.metrics(LEAD_FIVE, expense_change_pct=3)["stress_test"]["change_vs_base_case"]
        check("A7 LEAD stress test: computed change in gross margin $", delta["gross_margin_usd"]["change"], -5_095_280, 1)
        check("A7 LEAD stress test: computed change in projected net settlement $", delta["total_monies_owed_usd"]["change"], -5_006_553, 1)
        check("A7 LEAD stress test: changes are scenario minus base case, line by line",
              all(v["change"] == v["scenario"] - v["base_case"] for k, v in delta.items() if k.endswith("_usd")), True)
        # The discount sensitivity as a query would compute it, against values from pandas on the raw CSV (to the cent,
        # allowing for summation order), and the identity benchmark − expense = savings.
        q = wh.query(f'SELECT sum("Total benchmark") * 0.98 / 0.97, sum("Total projected expenditures"), '
                     f'sum("Total benchmark") * 0.98 / 0.97 - sum("Total projected expenditures") FROM "{lead.spec.table}" '
                     f'WHERE "Benchmark discount" = 0.03', 5, program="LEAD")["rows"][0]
        check("C4 discount sensitivity: benchmark at 2% $", q[0], 211_919_426_723.16, 0.05)
        check("C4 discount sensitivity: expense unchanged $", q[1], 197_434_764_474.57, 0.05)
        check("C4 discount sensitivity: gross savings at 2% $", q[2], 14_484_662_248.59, 0.05)
        check("C4 discount sensitivity: query result keeps benchmark − expense = savings", abs(q[0] - q[1] - q[2]) <= 0.011, True)
        check("A7 LEAD stress test: pooled vs standalone difference explained",
              hot["pooled_vs_standalone_note"].startswith("Pooled and standalone differ"), True)
        check("A7 LEAD stress test: no base-case per-TIN settlement", "sum_of_tin_projected_net_settlement_usd" in hot, False)

    if mssp:
        m = mssp.metrics(MSSP_THREE, target_mlr=0.90)
        c = m["combined"]
        check("B4 MSSP combined MLR", round(c["mlr"] * 100, 1), 98.2)
        check("B4 MSSP benchmark $B", round(c["benchmark_usd"] / 1e9, 2), 3.69)
        check("B4 MSSP margin $M", round(c["gross_margin_usd"] / 1e6, 1), 67.8)
        check("B4 MSSP person-years", round(c["person_years"]), 231_282, 1)
        check("B4 MSSP shared savings $M", round(c["shared_savings_or_losses_usd"] / 1e6, 1), 50.9)
        check("B4 MSSP cap not binding", c["cap_binding"], False)
        check("B4 MSSP financial guarantee $M", round(c["financial_guarantee_usd"] / 1e6, 1), 16.0)
        cohorts = {x["cohort"]: round(x["mlr"] * 100, 1) for x in m["cohorts"]}
        check("B4 MSSP cohort MLRs", [cohorts[k] for k in ("ESRD", "Disabled", "Aged / dual", "Aged / non-dual")],
              [98.6, 98.5, 95.0, 98.4])
        w = mssp.metrics(["954373071", "954415773", "721524529"])
        check("B8 MSSP shared-NPI warning", any("sharing one NPI" in x for x in w["warnings"]), True)
        check("B8 MSSP MLR", round(w["combined"]["mlr"] * 100, 1), 91.6)
    if lead and mssp:
        from app.portfolio import compare_programs
        p = compare_programs(agent.calcs, MSSP_THREE)["programs"]
        check("B5 LEAD side: benchmark $B / MLR / shared $M",
              [round(p["LEAD"]["benchmark_usd"] / 1e9, 2), round(p["LEAD"]["mlr"] * 100, 1), round(p["LEAD"]["shared_result_usd"] / 1e6, 1)],
              [4.40, 96.1, 167.5])
        check("B5 MSSP side: benchmark $B / MLR / shared $M",
              [round(p["MSSP"]["benchmark_usd"] / 1e9, 2), round(p["MSSP"]["mlr"] * 100, 1), round(p["MSSP"]["shared_result_usd"] / 1e6, 1)],
              [3.69, 98.2, 50.9])

    # ---- guard rails ------------------------------------------------------------------------------------
    if lead and mssp:
        other = wh.tables_for("MSSP")[0]
        text, _ = agent._run_tool("run_sql", {"sql": f'SELECT count(*) FROM "{other}"', "purpose": "x"}, {"program": "LEAD"})
        check("run_sql in a LEAD chat cannot read the MSSP table", "error" in json.loads(text), True)
        text, _ = agent._run_tool("run_sql", {"sql": f'WITH t AS (SELECT * FROM main."{other}") SELECT count(*) FROM t',
                                              "purpose": "x"}, {"program": "LEAD"})
        check("... nor through a CTE / schema-qualified name", "error" in json.loads(text), True)
    for pid in wh.programs:
        table = wh.tables_for(pid)[0]
        text, block = agent._run_tool("run_sql", {"sql": f'SELECT * FROM "{table}"', "purpose": "x"}, {"program": pid})
        res = json.loads(text)
        check(f"{pid} SELECT * result to Claude is within the size cap", len(text) <= config.MAX_RESULT_CHARS_TO_CLAUDE + 5000, True)
        check(f"{pid} SELECT * is cut short or refused as too wide", bool(res.get("truncated") or "error" in res), True)
        text, block = agent._run_tool("show_table", {"sql": f'SELECT * FROM "{table}"', "title": "x"}, {"program": pid})
        check(f"{pid} SELECT * table to the browser is within the size cap",
              len(json.dumps(block)) <= config.MAX_RESULT_CHARS_TO_UI + 200_000 and len(text) <= config.MAX_RESULT_CHARS_TO_CLAUDE + 5000, True)
    if lead:
        _, block = agent._run_tool("create_chart", {
            "title": "Median MLR by class", "chart_type": "bar", "x": "c", "y": ["Median MLR %"], "value_format": "percent",
            "sql": f'SELECT "ACO spending classification" AS c, round(100 * median("Pre-sharing MLR = expense / benchmark"), 2) '
                   f'AS "Median MLR %" FROM "{lead.spec.table}" WHERE "Total benchmark" > 0 GROUP BY 1 ORDER BY 1'}, {"program": "LEAD"})
        check("chart block: percent charts carry percentage values and say so",
              (block.get("percent_scale"), block["datasets"][0]["data"]), ("percent", [97.97, 94.41]))
    text = json.dumps(wh.query("SELECT repeat('x', 1000000) AS payload", 200, max_chars=config.MAX_RESULT_CHARS_TO_CLAUDE))
    check("one huge cell is cut", len(text) < 10_000, True)

    if lead:
        state = {"program": "LEAD", "portfolio": list(LEAD_FIVE), "target_mlr": 0.85}
        agent._run_tool("portfolio_metrics", {"action": "current", "save": False, "target_mlr": 0.9}, state)
        check("a what-if (save=false) leaves the saved target alone", state["target_mlr"], 0.85)
        agent._run_tool("portfolio_metrics", {"action": "add", "tins": ["910214500"], "expense_change_pct": 3}, state)
        check("a stress test leaves the saved portfolio alone", state["portfolio"], LEAD_FIVE)
        agent._run_tool("portfolio_metrics", {"action": "current", "target_mlr": 0.9}, state)
        check("stating a target saves it", state["target_mlr"], 0.9)
        # A portfolio far larger than anyone types: what goes back to Claude must stay small.
        big = [r[0] for r in wh.con.execute(f'SELECT "TIN" FROM "{lead.spec.table}" LIMIT 10000').fetchall()]
        state = {"program": "LEAD"}
        text, block = agent._run_tool("portfolio_metrics", {"tins": big, "target_mlr": 0.9}, state)
        check("10,000-TIN portfolio: result to Claude under 100k characters", len(text) < 100_000, True)
        check("10,000-TIN portfolio: all TINs saved", len(state["portfolio"]) > 9_900, True)
        check("10,000-TIN portfolio: browser table capped with a TOTAL row",
              (len(block["rows"]), block["rows"][-1][0], block["truncated"]), (config.MAX_ROWS_TO_UI + 1, "TOTAL", True))
        text, _ = agent._run_tool("portfolio_suggest", {"target_mlr": 0.85}, state)
        check("10,000-TIN portfolio: suggestion result under 100k characters", len(text) < 100_000, True)

    # ---- earlier results stay readable; reasoning blocks are replayed only within the current question -------
    from app.agent import ARCHIVE_KEY, _prepare, archive_results, find_result, public_state, strip_thinking

    def turn(n: int, result: str, thinking: bool = True) -> list[dict]:
        think = [{"type": "thinking", "thinking": "", "signature": f"sig{n}"}] if thinking else []
        return [{"role": "user", "content": [{"type": "text", "text": f"question {n}"}]},
                {"role": "assistant", "content": think + [{"type": "tool_use", "id": f"toolu_{n}", "name": "run_sql",
                                                           "input": {"sql": f"SELECT {n}"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"toolu_{n}", "content": result}]},
                {"role": "assistant", "content": [{"type": "text", "text": f"answer {n}"}]}]

    long = "row " * 2000
    hist = turn(1, long) + turn(2, "small") + turn(3, long)[:3]          # question 3 is still being answered
    sent = _prepare(hist)
    old_result = sent[2]["content"][0]["content"]
    check("earlier result: shortened in what the model sees, with its id", (len(old_result) < 2500, "toolu_1" in old_result), (True, True))
    check("earlier result: the stored transcript keeps it in full", hist[2]["content"][0]["content"], long)
    text, block = agent._run_tool("recall_result", {"result_id": "toolu_1"}, {}, hist)
    check("earlier result: recalled in full by id", (text, block["ok"]), (long, True))
    text, block = agent._run_tool("recall_result", {"result_id": "toolu_nope"}, {}, hist)
    check("earlier result: an unknown id is an error, not a guess", ('"error"' in text[:20], block["ok"]), (True, False))
    kinds = [[c["type"] for c in m["content"]] for m in sent]
    check("reasoning blocks: dropped from earlier questions", "thinking" in kinds[1] or "thinking" in kinds[5], False)
    check("reasoning blocks: kept for the question being answered", kinds[9][0], "thinking")
    check("reasoning blocks: the stored transcript is left alone by the request copy", hist[1]["content"][0]["type"], "thinking")
    check("reasoning blocks: removed once the question is answered",
          (strip_thinking(hist), any(c["type"] == "thinking" for m in hist for c in m["content"])), (True, False))
    st: dict = {"portfolio": ["1"]}
    kept = archive_results(turn(1, long, False) + turn(2, "small", False), st)
    check("summarized turns: their results are archived", [r["id"] for r in kept], ["toolu_1", "toolu_2"])
    check("summarized turns: an archived result is still recalled in full", find_result([], st, "toolu_1"), long)
    check("summarized turns: the archive stays on the server", (ARCHIVE_KEY in st, public_state(st)), (True, {"portfolio": ["1"]}))
    keep_chars = config.RESULT_ARCHIVE_CHARS
    config.RESULT_ARCHIVE_CHARS = len(long) + 10
    try:
        archive_results(turn(4, long, False), st)
        check("summarized turns: the archive is capped, newest kept", [r["id"] for r in st[ARCHIVE_KEY]], ["toolu_2", "toolu_4"])
    finally:
        config.RESULT_ARCHIVE_CHARS = keep_chars

    # ---- blank expense is not zero cost -------------------------------------------------------------------
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE synth AS SELECT CAST(i AS VARCHAR) tin, CAST(i AS VARCHAR) npi, 'Org ' || i org, 'Low' cls, "
                "1000.0 py, 1000.0 benes, 1000000.0 bm, CASE WHEN i = 7 THEN NULL ELSE 900000.0 + i * 1000 END ex FROM range(50) t(i)")
    spec = LeadSpec(program="SYNTH", table="synth", tin="tin", npi="npi", org="org", cls="cls", cls_header="Class", py="py",
                    benes="benes", bm_usd="bm", exp_usd="ex", cohorts=[], net_key="net_shared_savings_usd")
    calc = PortfolioCalc(Warehouse(con), spec)
    m = calc.metrics(["7", "8"])
    check("blank expense: TIN excluded from the totals", (m["tin_count"], m["combined"]["expense_usd"]), (1, 908000))
    check("blank expense: warning given", any("no projected expense" in w for w in m["warnings"]), True)
    s = calc.suggest(["8"], 0.95)
    listed = [t["tin"] for t in s["candidates"]["largest_by_benchmark"] + s["candidates"]["largest_by_margin"]]
    check("blank expense: never offered as a candidate", "7" in listed, False)
    check("blank expense: not counted as screened", s["candidates"]["screened"], 48)
    con.close()
    return out
