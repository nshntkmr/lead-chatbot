"""Run the eval suite: TESTING.md, automated.

    python -m evals.run --offline          deterministic checks only (no model calls, free, under a minute)
    python -m evals.run                    offline checks + every chat case against the configured model
    python -m evals.run --only A4-A7,B8    chosen cases        --list   show the case ids
    python -m evals.run --concurrency 2    chats in parallel (default 4)
    python -m evals.run --no-judge         skip the model judge (weaker: see below)

Chat cases call the model in .env (ANTHROPIC_MODEL), so a full run costs a few dollars; the total is printed.
Nothing is written to app.db. A JSON report with every answer goes to evals/results/. Exit code 1 on any failure.
Run it after every change to app/agent.py, app/portfolio.py or data/context*.md.

How answers are graded (evals/grade.py): each expected figure must be shown, with the right sign where the sign
is explicit, AND a model judge must agree that the answer states that figure for that metric with the right
direction and that the prose does not contradict its tables. The judge is itself tested on every run against
answers it must reject. With --no-judge only the first half runs: a figure shown anywhere counts, so use that
for a quick look, never as evidence that answers are right.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path

from app import config, pricing
from app.agent import Agent
from app.data import Warehouse

from . import grade as g
from . import offline, offline_infra
from .cases import CASES, Case


def _cost(msg) -> float:
    u = msg.usage
    n = lambda k: int(getattr(u, k, 0) or 0)
    return pricing.cost_usd(config.ANTHROPIC_MODEL, n("input_tokens"), n("output_tokens"),
                            n("cache_creation_input_tokens"), n("cache_read_input_tokens"))[0]


async def run_case(agent: Agent, case: Case, sem: asyncio.Semaphore, use_judge: bool) -> dict:
    async with sem:
        history, state = [], {"program": case.program}
        result = {"id": case.id, "program": case.program, "turns": [], "cost_usd": 0.0, "judge_cost_usd": 0.0,
                  "calls": 0, "seconds": 0.0}
        t0 = time.time()
        for turn in case.turns:
            text, blocks, error = "", [], None
            try:
                async for ev in agent.run(history, turn.ask, state):
                    if ev["type"] == "text":
                        text += ev["text"]
                    elif ev["type"] == "block":
                        blocks.append(ev["block"])
                    elif ev["type"] == "usage":
                        cost, _ = pricing.cost_usd(ev["model"], ev["input"], ev["output"], ev["cache_write"], ev["cache_read"])
                        result["cost_usd"] += cost
                        result["calls"] += 1
            except Exception as e:   # a failed call fails the turn's checks; later turns still run
                error = f"{type(e).__name__}: {e}"[:300]
            full, nums = g.visible(text, blocks)
            checks = []
            for c in turn.checks:
                ok, detail = (False, error) if error else g.grade(c, full, nums, blocks, state)
                checks.append({"label": c["label"], "ok": ok, "detail": detail})
            contradictions: list[str] = []
            observations: list[str] = []   # judge remarks that do not fail the turn; printed for a human
            if use_judge and not error and any(c["kind"] == "num" for c in turn.checks):
                try:
                    j = await g.judge(agent.client, config.ANTHROPIC_MODEL, turn.ask, text, blocks, turn.checks)
                    result["judge_cost_usd"] += _cost(j["usage"])
                    contradictions, observations = j["contradictions"], j["observations"]
                    for i, c in enumerate(turn.checks):
                        if c["kind"] != "num":
                            continue
                        verdict, evidence = j["verdicts"].get(i, ("missing", "the judge returned no verdict"))
                        checks[i]["judge"] = verdict
                        if verdict != "correct":
                            checks[i]["ok"] = False
                            checks[i]["detail"] = f"judge: {verdict} — {evidence}"[:300]
                    checks.append({"label": "no two different numbers for the same metric", "ok": not contradictions,
                                   "detail": " | ".join(contradictions)[:400]})
                except Exception as e:
                    checks.append({"label": "judge ran", "ok": False, "detail": f"{type(e).__name__}: {e}"[:300]})
            result["turns"].append({"ask": turn.ask, "answer": text, "error": error, "checks": checks,
                                    "contradictions": contradictions, "observations": observations,
                                    "blocks": [{k: b.get(k) for k in ("type", "name", "title", "subtitle", "label", "sql", "ok",
                                                                      "detail", "value_format", "percent_scale")
                                                if b.get(k) not in (None, "")} for b in blocks],
                                    "state": json.loads(json.dumps(state))})
        result["seconds"] = round(time.time() - t0, 1)
        result["ok"] = all(c["ok"] for t in result["turns"] for c in t["checks"])
        return result


def _print_rows(title: str, rows: list[tuple[str, bool, str]]) -> int:
    bad = [(n, d) for n, ok, d in rows if not ok]
    print(title)
    for name, detail in bad:
        print(f"  FAIL  {name}: {detail}")
    print(f"  {len(rows) - len(bad)}/{len(rows)} passed")
    return len(bad)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the ACO Data Assistant eval suite.")
    ap.add_argument("--offline", action="store_true", help="deterministic checks only; no model calls")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--no-judge", action="store_true", help="skip the model judge (a figure shown anywhere then counts)")
    args = ap.parse_args()
    if args.list:
        for c in CASES:
            print(f"{c.id:8} {c.program:5} {c.turns[0].ask[:90]}")
        return 0
    logging.basicConfig(level=logging.CRITICAL if args.offline else logging.WARNING)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    wh = Warehouse.open()
    failed = 0

    if not args.only:
        failed += _print_rows(f"Offline checks: portfolio math and guard rails (app version {config.APP_VERSION})", offline.run(wh))
        logging.disable(logging.CRITICAL)   # these checks provoke the app's error paths on purpose
        try:
            infra = offline_infra.run()
        finally:
            logging.disable(logging.NOTSET)
        failed += _print_rows("Offline checks: locking, rebuilds, deadlines, size guard, rendering", infra)
        failed += _print_rows("Offline checks: the grader rejects known-bad answers", g.deterministic_selftest())
    if args.offline:
        return 1 if failed else 0

    wanted = {x.strip() for x in args.only.split(",") if x.strip()}
    cases = [c for c in CASES if not wanted or c.id in wanted]
    unknown = wanted - {c.id for c in cases}
    if unknown:
        print(f"Unknown case id(s): {', '.join(sorted(unknown))}. Use --list.")
        return 2
    cases = [c for c in cases if c.program in wh.programs]
    agent = Agent(wh)
    use_judge = not args.no_judge
    extra_cost = 0.0

    async def go() -> list[dict]:   # one event loop for the judge self-test and the cases: they share the client
        nonlocal failed, extra_cost
        if use_judge:
            rows, usages = await g.judge_selftest(agent.client, config.ANTHROPIC_MODEL)
            extra_cost += sum(_cost(u) for u in usages)
            bad = _print_rows("\nJudge self-test: it must reject a flipped sign, a prose/table contradiction and a wrong cohort", rows)
            failed += bad
            if bad:
                print("  The judge cannot be trusted on this model; chat results below are NOT evidence of correctness.")
        else:
            print("\nJudge skipped (--no-judge): a figure shown anywhere in the answer counts. Not evidence of correctness.")
        print(f"\nChat cases: {len(cases)} against {config.ANTHROPIC_MODEL} ({config.CLAUDE_PROVIDER})")
        sem = asyncio.Semaphore(max(1, args.concurrency))
        return await asyncio.gather(*(run_case(agent, c, sem, use_judge) for c in cases))

    t0 = time.time()
    results = asyncio.run(go())
    total_checks = passed_checks = 0
    for r in results:
        checks = [c for t in r["turns"] for c in t["checks"]]
        total_checks += len(checks)
        passed_checks += sum(c["ok"] for c in checks)
        print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['id']:8} {sum(c['ok'] for c in checks)}/{len(checks)} checks  "
              f"{r['calls']} calls  ${r['cost_usd'] + r['judge_cost_usd']:.2f}  {r['seconds']:.0f}s")
        for i, t in enumerate(r["turns"], 1):
            for c in t["checks"]:
                if not c["ok"]:
                    print(f"          turn {i}: {c['label']}" + (f"  ({c['detail']})" if c["detail"] else ""))
    notes = [(r["id"], i, o) for r in results for i, t in enumerate(r["turns"], 1) for o in t.get("observations") or []]
    if notes:
        print(f"\nJudge observations for a human to read ({len(notes)}; these do not fail a case):")
        for cid, i, o in notes:
            print(f"  {cid} turn {i}: {o[:260]}")
    bad_cases = sum(1 for r in results if not r["ok"])
    failed += bad_cases
    cost = sum(r["cost_usd"] for r in results)
    judge_cost = sum(r["judge_cost_usd"] for r in results) + extra_cost
    print(f"\n{len(results) - bad_cases}/{len(results)} cases passed, {passed_checks}/{total_checks} checks, "
          f"estimated cost ${cost + judge_cost:.2f} (answers ${cost:.2f}, judge ${judge_cost:.2f}), {time.time() - t0:.0f}s")
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"app_version": config.APP_VERSION, "model": config.ANTHROPIC_MODEL,
                                "provider": config.CLAUDE_PROVIDER, "judge": use_judge,
                                "cost_usd": round(cost + judge_cost, 4), "cases": results},
                               indent=1, default=str), encoding="utf-8")
    print(f"Report: {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
