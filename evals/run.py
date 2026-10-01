"""Run the eval suite: TESTING.md, automated.

    python -m evals.run --offline          deterministic checks only (no model calls, free, a few seconds)
    python -m evals.run                    offline checks + every chat case against the configured model
    python -m evals.run --only A4-A7,B8    chosen cases        --list   show the case ids
    python -m evals.run --concurrency 2    chats in parallel (default 4)

Chat cases call the model in .env (ANTHROPIC_MODEL), so a full run costs a few dollars; the total is printed.
Nothing is written to app.db. A JSON report with every answer goes to evals/results/. Exit code 1 on any failure.
Run it after every change to app/agent.py, app/portfolio.py or data/context*.md.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import re
import sys
import time
from pathlib import Path

from app import config, pricing
from app.agent import Agent
from app.data import Warehouse

from . import offline
from .cases import CASES, Case

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
                  r"(%|[kKmMbB]\b|bn\b|million\b|billion\b|thousand\b)?")
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def numbers_in(text: str) -> list[float]:
    """Every figure in a piece of text, with $1.2M / 1.2 million / 1,200,000 all read as 1200000."""
    out = []
    for m in _NUM.finditer(text.replace("*", "")):
        out.append(float(m.group(1).replace(",", "")) * _SCALE.get((m.group(2) or "").lower(), 1))
    return out


def visible(text: str, blocks: list[dict]) -> tuple[str, list[float]]:
    """What the user sees for one answer: all of its text, and every number in the text, tables and charts."""
    parts, nums = [text], []
    for b in blocks:
        parts += [str(b.get(k) or "") for k in ("title", "subtitle", "label", "detail")]
        for row in b.get("rows") or []:
            for v in row:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums.append(float(v))
                elif isinstance(v, str):
                    parts.append(v)
        for ds in b.get("datasets") or []:
            for v in ds.get("data") or []:
                v = v.get("y") if isinstance(v, dict) else v
                if isinstance(v, (int, float)):
                    nums.append(float(v))
        parts += [str(x) for x in b.get("labels") or []]
    full = "\n".join(parts)
    return full, nums + numbers_in(full)


def grade(check: dict, text: str, nums: list[float], blocks: list[dict], state: dict) -> tuple[bool, str]:
    kind = check["kind"]
    if kind == "num":
        want, tol = abs(check["value"]), check["tol"] + 1e-9
        near = min(nums, key=lambda v: abs(abs(v) - want), default=None)
        ok = near is not None and abs(abs(near) - want) <= tol
        return ok, "" if ok else f"closest figure shown: {near:,.4g}" if near is not None else "no figures shown"
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
    raise ValueError(kind)


async def run_case(agent: Agent, case: Case, sem: asyncio.Semaphore) -> dict:
    async with sem:
        history, state = [], {"program": case.program}
        result = {"id": case.id, "program": case.program, "turns": [], "cost_usd": 0.0, "calls": 0, "seconds": 0.0}
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
            full, nums = visible(text, blocks)
            checks = []
            for c in turn.checks:
                ok, detail = (False, error) if error else grade(c, full, nums, blocks, state)
                checks.append({"label": c["label"], "ok": ok, "detail": detail})
            result["turns"].append({"ask": turn.ask, "answer": text, "error": error, "checks": checks,
                                    "blocks": [{k: b.get(k) for k in ("type", "name", "title", "subtitle", "label", "sql", "ok", "detail")
                                                if b.get(k) not in (None, "")} for b in blocks],
                                    "state": json.loads(json.dumps(state))})
        result["seconds"] = round(time.time() - t0, 1)
        result["ok"] = all(c["ok"] for t in result["turns"] for c in t["checks"])
        return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the ACO Data Assistant eval suite.")
    ap.add_argument("--offline", action="store_true", help="deterministic checks only; no model calls")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    if args.list:
        for c in CASES:
            print(f"{c.id:8} {c.program:5} {c.turns[0].ask[:90]}")
        return 0
    logging.basicConfig(level=logging.WARNING)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    wh = Warehouse.open()
    failed = 0

    if not args.only:
        rows = offline.run(wh)
        print(f"Offline checks (app version {config.APP_VERSION})")
        for name, ok, detail in rows:
            if not ok:
                print(f"  FAIL  {name}: {detail}")
        bad = sum(1 for _, ok, _ in rows if not ok)
        failed += bad
        print(f"  {len(rows) - bad}/{len(rows)} passed")
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

    async def go() -> list[dict]:
        sem = asyncio.Semaphore(max(1, args.concurrency))
        return await asyncio.gather(*(run_case(agent, c, sem) for c in cases))

    print(f"\nChat cases: {len(cases)} against {config.ANTHROPIC_MODEL} ({config.CLAUDE_PROVIDER})")
    t0 = time.time()
    results = asyncio.run(go())
    total_checks = passed_checks = 0
    for r in results:
        checks = [c for t in r["turns"] for c in t["checks"]]
        total_checks += len(checks)
        passed_checks += sum(c["ok"] for c in checks)
        print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['id']:8} {sum(c['ok'] for c in checks)}/{len(checks)} checks  "
              f"{r['calls']} calls  ${r['cost_usd']:.2f}  {r['seconds']:.0f}s")
        for i, t in enumerate(r["turns"], 1):
            for c in t["checks"]:
                if not c["ok"]:
                    print(f"          turn {i}: {c['label']}" + (f"  ({c['detail']})" if c["detail"] else ""))
    bad_cases = sum(1 for r in results if not r["ok"])
    failed += bad_cases
    cost = sum(r["cost_usd"] for r in results)
    print(f"\n{len(results) - bad_cases}/{len(results)} cases passed, {passed_checks}/{total_checks} checks, "
          f"estimated cost ${cost:.2f}, {time.time() - t0:.0f}s")
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"app_version": config.APP_VERSION, "model": config.ANTHROPIC_MODEL,
                                "provider": config.CLAUDE_PROVIDER, "cost_usd": round(cost, 4), "cases": results},
                               indent=1, default=str), encoding="utf-8")
    print(f"Report: {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
