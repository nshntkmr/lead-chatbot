"""Deterministic checks of the plumbing around the model: turn locking, the rebuild manifest, multi-file
extracts, query deadlines, the final result-size guard, and how chart percentages are rendered. Everything
runs against temporary files; the real app.db, warehouse and data folder are not touched."""
from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import duckdb

from app import config, data, store
from app.agent import Agent, make_calcs, within_budget
from app.data import QueryBusy, QueryTimeout, Warehouse
from app.portfolio import LeadSpec, PortfolioCalc, PortfolioUnavailable, build_spec

HEAD = ["TIN", "NPI", "Organization", "Benchmark PBPM after discount and earned quality", "Projected expense PBPM",
        "Person years after exposure adjustment", "Total benchmark"]


def _write(path: Path, tins: list[int], header: list[str] = HEAD) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for t in tins:
            w.writerow([t, 9000 + t, f"Org {t}", 1000.0, 900.0 + t, 100.0, 1_200_000.0] + [1] * (len(header) - len(HEAD)))


class _Temp:
    """Point the app's settings at a scratch folder for the duration of a block."""
    KEYS = ("SOURCE_DIR", "DATA_DIR", "WAREHOUSE_PATH", "APP_DB_PATH")

    def __enter__(self) -> Path:
        self.saved = {k: getattr(config, k) for k in self.KEYS}
        self.dir = Path(tempfile.mkdtemp(prefix="aco-evals-"))
        config.SOURCE_DIR = config.DATA_DIR = self.dir
        config.WAREHOUSE_PATH = self.dir / "warehouse.duckdb"
        config.APP_DB_PATH = self.dir / "app.db"
        return self.dir

    def __exit__(self, *exc) -> None:
        for k, v in self.saved.items():
            setattr(config, k, v)
        shutil.rmtree(self.dir, ignore_errors=True)


def run() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def check(name: str, got, want) -> None:
        out.append((name, got == want, f"got {got!r}, expected {want!r}"))

    # ---- one question at a time per chat -----------------------------------------------------------------
    with _Temp():
        store.init()
        store.upsert_user("eval", "not-a-real-password")
        cid = store.create_conversation("eval", "t", {"program": "LEAD"})
        t1 = store.acquire_turn("eval", cid, 60)
        check("turn lock: first request gets it", bool(t1), True)
        check("turn lock: a second request for the same chat is refused", store.acquire_turn("eval", cid, 60), None)
        check("turn lock: a save without the lock's token writes nothing",
              store.save_conversation("eval", cid, [{"x": 1}], [], {}, token="someone-else"), False)
        check("turn lock: the holder's save succeeds and releases",
              (store.save_conversation("eval", cid, [{"role": "user"}], [], {}, token=t1), bool(store.acquire_turn("eval", cid, 60))),
              (True, True))
        cid2 = store.create_conversation("eval", "t2", {"program": "LEAD"})
        stale = store.acquire_turn("eval", cid2, -1)            # already expired: its holder "died"
        fresh = store.acquire_turn("eval", cid2, 60)
        check("turn lock: an expired lock can be taken over", bool(fresh), True)
        store.save_conversation("eval", cid2, [{"turn": "new"}], [], {}, token=fresh)
        check("turn lock: the expired holder cannot overwrite the newer transcript",
              (store.save_conversation("eval", cid2, [{"turn": "old"}], [], {}, token=stale),
               store.get_conversation("eval", cid2)["api_messages"]), (False, [{"turn": "new"}]))

        # The handler itself: two requests accepted before either stream starts (the reported race).
        from fastapi import HTTPException
        from app import main
        cid3 = store.create_conversation("eval", "t3", {"program": "LEAD"})
        body = main.ChatIn(message="hello", conversation_id=cid3)
        user = {"username": "eval"}
        saved_runtime = dict(main.runtime)
        main.runtime["agent"] = object()
        try:
            asyncio.run(main.chat(body, user))                  # response returned, stream not started
            try:
                asyncio.run(main.chat(body, user))
                second = "accepted"
            except HTTPException as e:
                second = e.status_code
        finally:
            main.runtime.clear()
            main.runtime.update(saved_runtime)
        check("chat handler: a second request for the same chat gets 409 before any stream starts", second, 409)

        # ---- login lockout: counted in app.db, per real client address ---------------------------------------
        from starlette.requests import Request
        from starlette.responses import Response

        def request(peer: str, forwarded: str | None = None) -> Request:
            headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
            return Request({"type": "http", "method": "POST", "path": "/api/login", "headers": headers, "client": (peer, 50000)})

        check("lockout: 8 attempts are let through and the 9th is refused",
              [store.begin_login_attempt("198.51.100.1", 8, 900) for _ in range(9)], [True] * 8 + [False])
        check("lockout: another address is not affected", store.begin_login_attempt("198.51.100.2", 8, 900), True)
        child = subprocess.run(
            [sys.executable, "-c", "from app import store; print(store.begin_login_attempt('198.51.100.1', 8, 900))"],
            capture_output=True, text=True, timeout=120, cwd=str(Path(__file__).parent.parent),
            env=dict(os.environ, APP_DB_PATH=str(config.APP_DB_PATH), SECRET_KEY="eval"))
        check("lockout: a second worker process sees the same lock", child.stdout.strip(), "False")
        store.clear_login_attempts("198.51.100.1")
        check("lockout: a successful sign-in clears the count", store.begin_login_attempt("198.51.100.1", 8, 900), True)
        check("lockout: it lifts once the window has passed",
              (store.begin_login_attempt("198.51.100.3", 1, 0.3), store.begin_login_attempt("198.51.100.3", 1, 0.3),
               time.sleep(0.4), store.begin_login_attempt("198.51.100.3", 1, 0.3)), (True, False, None, True))
        results: list[bool] = []
        burst = [threading.Thread(target=lambda: results.append(store.begin_login_attempt("198.51.100.4", 8, 900)))
                 for _ in range(30)]
        [t.start() for t in burst]
        [t.join() for t in burst]
        check("lockout: 30 guesses arriving at once still let only 8 through", sum(results), 8)

        codes = []
        for _ in range(9):
            try:
                main.login(main.LoginIn(username="eval", password="wrong-guess"), request("203.0.113.9"), Response())
                codes.append(200)
            except HTTPException as e:
                codes.append(e.status_code)
        check("login handler: eight wrong passwords get 401, the ninth gets 429", codes, [401] * 8 + [429])
        try:
            main.login(main.LoginIn(username="eval", password="not-a-real-password"), request("203.0.113.9"), Response())
            locked = "signed in"
        except HTTPException as e:
            locked = e.status_code
        check("login handler: while locked out, even the right password is refused", locked, 429)
        ok = main.login(main.LoginIn(username="eval", password="not-a-real-password"), request("203.0.113.10"), Response())
        check("login handler: the right password from another address signs in", ok, {"ok": True})

        saved_hops = config.TRUSTED_PROXY_HOPS
        try:
            config.TRUSTED_PROXY_HOPS = 0
            check("client address: directly connected, a forged X-Forwarded-For is ignored",
                  main.client_ip(request("203.0.113.9", "1.2.3.4")), "203.0.113.9")
            config.TRUSTED_PROXY_HOPS = 1
            check("client address: behind one proxy, the entry the proxy added is used, not the one the client sent",
                  main.client_ip(request("10.0.0.5", "1.2.3.4, 203.0.113.7")), "203.0.113.7")
            check("client address: a port is stripped (Azure App Service sends ip:port)",
                  main.client_ip(request("10.0.0.5", "203.0.113.7:51234")), "203.0.113.7")
            check("client address: IPv6 with and without a port",
                  (main.client_ip(request("10.0.0.5", "[2001:db8::1]:443")), main.client_ip(request("10.0.0.5", "2001:db8::1"))),
                  ("2001:db8::1", "2001:db8::1"))
            check("client address: no header from the proxy falls back to the peer",
                  main.client_ip(request("10.0.0.5")), "10.0.0.5")
            config.TRUSTED_PROXY_HOPS = 2
            check("client address: behind two proxies, the second entry from the right",
                  main.client_ip(request("10.0.0.5", "1.2.3.4, 203.0.113.7, 10.0.0.9")), "203.0.113.7")
        finally:
            config.TRUSTED_PROXY_HOPS = saved_hops

    # ---- warehouse rebuild follows the source files ----------------------------------------------------------
    with _Temp() as d:
        _write(d / "LEAD_part1.csv", list(range(1, 6)))
        _write(d / "LEAD_part2.csv", list(range(6, 9)))
        data.build_warehouse()
        con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
        tables = con.execute("SELECT table_name, source_file FROM _tables").fetchall()
        rows = con.execute(f'SELECT count(*), count(DISTINCT "TIN") FROM "{tables[0][0]}"').fetchone()
        tin_type = con.execute("SELECT data_type FROM information_schema.columns WHERE column_name = 'TIN'").fetchone()[0]
        con.close()
        check("multi-file extract: files with the same header load as one table", len(tables), 1)
        check("multi-file extract: the table has every file's rows", rows, (8, 8))
        check("multi-file extract: both files are recorded as its source", tables[0][1], "LEAD_part1.csv + LEAD_part2.csv")
        check("multi-file extract: TIN stays text", tin_type, "VARCHAR")
        files = data._data_files()
        check("manifest: unchanged files do not trigger a rebuild", data._is_stale(files, config.WAREHOUSE_PATH), False)
        (d / "LEAD_part2.csv").unlink()
        check("manifest: removing a source file triggers a rebuild", data._is_stale(data._data_files(), config.WAREHOUSE_PATH), True)
        data.build_warehouse()
        con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
        n = con.execute(f'SELECT count(*) FROM "{tables[0][0]}"').fetchone()[0]
        con.close()
        check("manifest: after the rebuild the removed file's rows are gone", n, 5)
        _write(d / "LEAD_part1.csv", [1, 2, 3, 4, 7])           # same size, different content…
        old = time.time() - 86400 * 30
        os.utime(d / "LEAD_part1.csv", (old, old))             # …copied in with an OLDER timestamp
        check("manifest: a replacement with an older timestamp triggers a rebuild",
              data._is_stale(data._data_files(), config.WAREHOUSE_PATH), True)

    # ---- portfolio math refuses layouts that would make its totals wrong -------------------------------------
    with _Temp() as d:
        _write(d / "LEAD_a.csv", [1, 2, 3])
        _write(d / "LEAD_b.csv", [4, 5], HEAD + ["Extra column"])   # different header: stays a second table
        wh = Warehouse.open()
        try:
            try:
                build_spec(wh, "LEAD")
                got = "used one table silently"
            except PortfolioUnavailable as e:
                got = "refused" if "2 LEAD tables" in str(e) else str(e)
            check("two tables with headline columns: portfolio math is refused, not run on the first", got, "refused")
            calcs, errors = make_calcs(wh)
            agent = Agent.__new__(Agent)
            agent.wh, agent.programs, agent.default_program, agent.calcs, agent.calc_errors = wh, wh.programs, None, calcs, errors
            text, _ = agent._run_tool("portfolio_metrics", {"tins": ["1"]}, {"program": "LEAD"})
            check("...and the tool tells the user why", "2 LEAD tables" in json.loads(text).get("error", ""), True)
        finally:
            wh.con.close()
    with _Temp() as d:
        _write(d / "LEAD_dup.csv", [1, 2, 2, 3])
        wh = Warehouse.open()
        try:
            try:
                build_spec(wh, "LEAD")
                got = "accepted"
            except PortfolioUnavailable as e:
                got = "refused" if "repeat a TIN" in str(e) else str(e)
            check("a TIN on two rows: portfolio math is refused", got, "refused")
        finally:
            wh.con.close()

    # ---- every query has a deadline and a slot ----------------------------------------------------------------
    con = duckdb.connect(":memory:")
    wh = Warehouse(con)
    t0 = time.time()
    try:
        wh.execute("SELECT sum(a.range * b.range) FROM range(100000000) a, range(100000) b", timeout=0.5)
        got = "finished"
    except QueryTimeout:
        got = "stopped"
    check("deadline: a runaway query is stopped", (got, time.time() - t0 < 10), ("stopped", True))
    for _ in range(config.MAX_CONCURRENT_QUERIES):
        wh._slots.acquire()
    try:
        wh.execute("SELECT 1", timeout=0.2)
        got = "ran"
    except QueryBusy:
        got = "busy"
    finally:
        for _ in range(config.MAX_CONCURRENT_QUERIES):
            wh._slots.release()
    check("bounded concurrency: with every slot taken a query waits, then reports busy", got, "busy")
    src = (Path(__file__).parent.parent / "app" / "portfolio.py").read_text(encoding="utf-8")
    check("deadline: the portfolio calculator has no query path outside Warehouse.execute", ".con.cursor()" in src or ".con.execute(" in src, False)

    # ---- the final size guard, on the case that slipped past the per-list caps ------------------------------
    con.execute("CREATE TABLE synth AS SELECT CAST(100000 + i AS VARCHAR) tin, '777' npi, 'Org ' || i org, 'Low' cls, "
                "1000.0 py, 1000.0 benes, 1000000.0 bm, 900000.0 ex FROM range(10000) t(i)")
    spec = LeadSpec(program="SYNTH", table="synth", tin="tin", npi="npi", org="org", cls="cls", cls_header="Class", py="py",
                    benes="benes", bm_usd="bm", exp_usd="ex", cohorts=[], net_key="net_shared_savings_usd")
    agent = Agent.__new__(Agent)
    agent.wh, agent.programs, agent.default_program = wh, {}, None
    agent.calcs, agent.calc_errors = {"SYNTH": PortfolioCalc(wh, spec)}, {}
    tins = [str(100000 + i) for i in range(10000)]
    text, _ = agent._run_tool("portfolio_metrics", {"tins": tins}, {"program": "SYNTH"})
    warning = max(json.loads(text)["warnings"], key=len)
    check("10,000 TINs sharing one NPI: the warning stays short", len(warning) < 1000, True)
    check("10,000 TINs sharing one NPI: the whole result is within the size cap",
          len(within_budget(text)) <= config.MAX_RESULT_CHARS_TO_CLAUDE, True)
    huge = json.dumps({"note": "x" * 500_000, "items": [{"k": "y" * 300} for _ in range(5000)], "total": 42})
    cut = within_budget(huge)
    check("size guard: an uncapped field is cut and the result still parses, totals intact",
          (len(cut) <= config.MAX_RESULT_CHARS_TO_CLAUDE, json.loads(cut).get("total")), (True, 42))
    con.close()

    # ---- chart percentages: one representation, tested as rendered ---------------------------------------------
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, str(Path(__file__).parent / "render_check.js")], capture_output=True, text=True, timeout=60)
        shown = json.loads(r.stdout or "{}")
        check("rendered: a percent chart value of 87.35 is drawn as 87.35%", shown.get("new_percent_chart"), "87.35%")
        check("rendered: a small percentage (0.8) is drawn as 0.8%, not 80%", shown.get("new_percent_small"), "0.8%")
        check("rendered: charts saved before this version (fractions) still read 87.4%", shown.get("legacy_percent_chart"), "87.4%")
    else:
        out.append(("rendered chart percentages (needs Node.js on PATH)", True, "skipped: node not found"))
    return out
