"""Data layer: loads every CSV / Excel file in SOURCE_DIR (and DATA_DIR) into a local DuckDB
warehouse and exposes safe, read-only helpers that Claude's tools call."""
from __future__ import annotations

import csv
import datetime as dt
import decimal
import hashlib
import json
import logging
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from . import config
from .dictionary import STD_FIELDS, Dictionary, Entry, standardize

log = logging.getLogger(__name__)

DATA_EXTS = {".csv", ".xlsx", ".xlsm", ".xls"}


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------
def _table_name(stem: str, sheet: str | None = None) -> str:
    name = f"{stem}_{sheet}" if sheet else stem
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    if not name or name[0].isdigit():
        name = "t_" + name
    return name


def _is_dictionary(path: Path) -> bool:
    return "dictionary" in path.stem.lower()


def detect_program(filename: str) -> str:
    """Program id for a data file, from the keywords in config.PROGRAM_KEYWORDS."""
    stem = Path(filename).stem.upper()
    for k in config.PROGRAM_KEYWORDS:
        if re.search(rf"(^|[^A-Z]){re.escape(k)}([^A-Z]|$)", stem):
            return k
    return "DATA"


def _setting(value: str) -> str:
    """A memory size from the environment ('4GB', '512MB'), checked before it goes into a SET statement."""
    if not re.fullmatch(r"\d+(\.\d+)?\s?(KB|MB|GB|TB|KiB|MiB|GiB|TiB)", value, flags=re.I):
        raise RuntimeError(f"Not a memory size: {value!r} (use e.g. 4GB)")
    return value


def _qi(name: str) -> str:
    """Quote an identifier."""
    return '"' + name.replace('"', '""') + '"'


# Values pandas reads as missing by default. The CSV loader uses the same list so column types match
# warehouses built by earlier versions (which read CSVs through pandas).
_NULL_STRINGS = ["", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND", "1.#QNAN",
                 "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null"]


def _load_csv(con: duckdb.DuckDBPyConnection, paths: list[Path], tname: str) -> None:
    """Load a data CSV with DuckDB's own reader. It streams the file, so memory stays within the build
    connection's memory_limit however many rows there are (pandas needs the whole table in RAM: ~8 GB for
    200,000 rows of the 2,605-column extract). See config.BUILD_THREADS for why the build is single-threaded.
    Several files with the same header are read as one table, with column types inferred across all of them."""
    src = [str(p) for p in paths]
    lit = lambda s: "'" + s.replace("'", "''") + "'"
    opts = (f"header = true, delim = ',', quote = '\"', escape = '\"', strict_mode = false, "
            f"normalize_names = false, nullstr = [{', '.join(lit(s) for s in _NULL_STRINGS)}], "
            f"auto_type_candidates = ['BIGINT', 'DOUBLE', 'VARCHAR']")
    names = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv(?, {opts})", [src]).fetchall()]
    text = [n for n in names if n.strip() in config.TEXT_COLUMNS]
    types = ", types = {" + ", ".join(lit(n) + ": 'VARCHAR'" for n in text) + "}" if text else ""
    select = ", ".join(f"{_qi(n)} AS {_qi(n.strip())}" for n in names)
    # sample_size = -1: infer each column's type from every row, as pandas did.
    con.execute(f"CREATE TABLE {_qi(tname)} AS SELECT {select} FROM read_csv(?, {opts}, sample_size = -1{types})",
                [src])
    # Two pandas conventions the rest of the app (and the domain notes) rely on: a column of True/False is
    # BOOLEAN — but Yes/No stays text, which DuckDB's own boolean detection would convert — and an entirely
    # blank column is numeric.
    kept_text = {n.strip() for n in text}
    varchar = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? AND data_type = 'VARCHAR' "
        "ORDER BY ordinal_position", [tname]).fetchall() if r[0] not in kept_text]
    for i in range(0, len(varchar), 500):
        chunk = varchar[i:i + 500]
        exprs = ", ".join(f"count({_qi(n)}), count(*) FILTER (WHERE {_qi(n)} IN ('True', 'TRUE', 'true', 'False', "
                          f"'FALSE', 'false'))" for n in chunk)
        r = con.execute(f"SELECT count(*), {exprs} FROM {_qi(tname)}").fetchone()
        for j, n in enumerate(chunk):
            filled, boolean = r[1 + 2 * j], r[2 + 2 * j]
            if filled == 0:
                con.execute(f"ALTER TABLE {_qi(tname)} ALTER {_qi(n)} TYPE DOUBLE")
            elif filled == boolean == r[0]:
                con.execute(f"ALTER TABLE {_qi(tname)} ALTER {_qi(n)} TYPE BOOLEAN")


def _read_file(path: Path) -> dict[str, pd.DataFrame]:
    """Return {table_name: dataframe}. Excel files give one table per sheet. Used for Excel files and the
    (small) column dictionary; data CSVs go through _load_csv."""
    text_dtype = {c: str for c in config.TEXT_COLUMNS}
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=text_dtype, low_memory=False)
        return {_table_name(path.stem): df}
    sheets = pd.read_excel(path, sheet_name=None, dtype=text_dtype)
    if len(sheets) == 1:
        return {_table_name(path.stem): next(iter(sheets.values()))}
    return {_table_name(path.stem, s): df for s, df in sheets.items() if not df.empty}


def _data_files() -> list[Path]:
    dirs = [d for d in dict.fromkeys((config.SOURCE_DIR, config.DATA_DIR)) if d.is_dir()]
    found: dict[str, Path] = {}
    for d in dirs:
        for p in d.iterdir():
            if (p.suffix.lower() in DATA_EXTS and not p.name.startswith("~$")
                    and not p.stem.lower().startswith("column_notes")):
                found.setdefault(p.name, p)   # the same file name in both folders is loaded once (SOURCE_DIR wins)
    return [found[name] for name in sorted(found)]


BUILD_FORMAT = "2"   # bump when the loader changes what it writes, so existing warehouses rebuild


def _manifest(files: list[Path]) -> list[tuple[str, int, int, str]]:
    """What the warehouse was built from: (name, size, modified time, content hash) per source file. The hash
    is filled only with VERIFY_SOURCE_HASH=true (it reads every byte of every extract at each start)."""
    out = [("__format__", 0, 0, BUILD_FORMAT)]
    for f in files:
        st = f.stat()
        digest = ""
        if config.VERIFY_SOURCE_HASH:
            h = hashlib.sha256()
            with f.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 22), b""):
                    h.update(block)
            digest = h.hexdigest()
        out.append((f.name, st.st_size, st.st_mtime_ns, digest))
    return sorted(out)


def _stored_manifest(wh: Path) -> list[tuple[str, int, int, str]] | None:
    """The manifest recorded in an existing warehouse; None when it has none (built by an earlier version)."""
    con = duckdb.connect(str(wh), read_only=True)
    try:
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = '_sources'").fetchone()[0]:
            return None
        return sorted(tuple(r) for r in con.execute("SELECT name, size, mtime_ns, sha256 FROM _sources").fetchall())
    finally:
        con.close()


def _is_stale(files: list[Path], wh: Path) -> bool:
    """True when the warehouse does not reflect exactly the source files now present: one was added, removed,
    resized, or replaced (including by a copy with an older timestamp)."""
    if not wh.exists():
        return True
    stored = _stored_manifest(wh)
    if stored is None:   # no manifest yet: the earlier rule, so an upgrade alone does not force a rebuild
        return wh.stat().st_mtime < max(f.stat().st_mtime for f in files)
    return stored != _manifest(files)


def _csv_header(path: Path) -> tuple[str, ...]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return tuple(c.strip() for c in next(csv.reader(f), []))


def build_warehouse(force: bool = False) -> None:
    """(Re)build the DuckDB file when it does not match the source files (see _is_stale)."""
    files = _data_files()
    if not files:
        raise RuntimeError(f"No CSV/Excel files found in {config.SOURCE_DIR}")
    wh = config.WAREHOUSE_PATH
    if not force and not _is_stale(files, wh):
        return
    log.info("Building data warehouse from %d file(s)…", len(files))
    manifest = _manifest(files)
    tmp = wh.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute(f"SET threads = {max(1, config.BUILD_THREADS)}")
        con.execute(f"SET memory_limit = '{_setting(config.BUILD_MEMORY_LIMIT)}'")
        con.execute("CREATE TABLE _column_dictionary (header VARCHAR, units VARCHAR, definition VARCHAR, notes VARCHAR, "
                    "sheet VARCHAR, cell VARCHAR, formula VARCHAR, source_type VARCHAR, program VARCHAR)")
        con.execute("CREATE TABLE _tables (table_name VARCHAR, source_file VARCHAR, program VARCHAR)")
        con.execute("CREATE TABLE _column_stats (table_name VARCHAR, column_name VARCHAR, distinct_count BIGINT, "
                    "constant_json VARCHAR)")
        con.execute("CREATE TABLE _sources (name VARCHAR, size BIGINT, mtime_ns BIGINT, sha256 VARCHAR)")
        con.executemany("INSERT INTO _sources VALUES (?, ?, ?, ?)", [list(m) for m in manifest])

        def registered(tname: str, source: str, program: str) -> None:
            con.execute("INSERT INTO _tables VALUES (?, ?, ?)", [tname, source, program])
            names = [r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
                [tname]).fetchall()]
            # Profiled once here rather than at every start-up (a scan of every column: ~13 s at 200,000 rows).
            con.executemany("INSERT INTO _column_stats VALUES (?, ?, ?, ?)",
                            [[tname, n, d, json.dumps(v)] for n, d, v in _column_stats(con, tname, names)])
            rows = con.execute(f"SELECT count(*) FROM {_qi(tname)}").fetchone()[0]
            log.info("  table %s [%s] from %s: %d rows x %d cols", tname, program, source, rows, len(names))

        # Data CSVs of one program with the same header are parts of one extract: they become one table, so
        # every tool (the portfolio calculator included) sees all of their rows.
        parts: dict[tuple[str, tuple[str, ...]], list[Path]] = {}
        for f in files:
            if f.suffix.lower() == ".csv" and not _is_dictionary(f):
                parts.setdefault((detect_program(f.name), _csv_header(f)), []).append(f)
        for (program, _), group in parts.items():
            tname = _table_name(group[0].stem)
            _load_csv(con, group, tname)
            registered(tname, " + ".join(f.name for f in group), program)

        for f in files:
            if f.suffix.lower() == ".csv" and not _is_dictionary(f):
                continue
            for tname, df in _read_file(f).items():
                if _is_dictionary(f):
                    d = standardize(df)
                    d["program"] = detect_program(f.name)
                    con.register("d", d)
                    con.execute("INSERT INTO _column_dictionary SELECT * FROM d")
                    con.unregister("d")
                    log.info("  dictionary %s: %d entries", f.name, len(d))
                    continue
                df.columns = [str(c).strip() for c in df.columns]
                con.register("df", df)
                con.execute(f'CREATE TABLE "{tname}" AS SELECT * FROM df')
                con.unregister("df")
                registered(tname, f.name, detect_program(f.name))
    finally:
        con.close()
    try:
        wh.unlink(missing_ok=True)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"The source files changed, but {wh.name} cannot be replaced because another process has "
                           f"it open. Stop the other app instance (or point WAREHOUSE_PATH elsewhere) and start again.") from e
    tmp.rename(wh)


def _column_stats(con: duckdb.DuckDBPyConnection, tname: str, names: list[str]) -> list[tuple[str, int, object]]:
    """(column, distinct count, the single value when there is exactly one) for every column of a table."""
    out = []
    for i in range(0, len(names), 100):   # small batches: each DISTINCT keeps its values in memory
        chunk = names[i:i + 100]
        exprs = ", ".join(f"count(DISTINCT {_qi(n)}), any_value({_qi(n)})" for n in chunk)
        r = con.execute(f"SELECT {exprs} FROM {_qi(tname)}").fetchone()
        out.extend((n, r[2 * j], _clean(r[2 * j + 1]) if r[2 * j] == 1 else None) for j, n in enumerate(chunk))
    return out


# --------------------------------------------------------------------------
# Read-only access
# --------------------------------------------------------------------------
class QueryTimeout(RuntimeError):
    """A query ran past its deadline and was stopped."""


class QueryBusy(RuntimeError):
    """No query slot became free within the deadline."""


@dataclass
class Column:
    table: str
    name: str
    dtype: str
    entry: Entry | None = None   # linked dictionary entry
    link: str | None = None      # exact | cell | pattern | note
    note: str | None = None      # curated definition from data/column_notes*.csv
    kind: str | None = None      # label | duplicate | raw | parameter | metric (from the notes file)
    distinct: int | None = None
    constant: object = None      # the single value when distinct == 1


@dataclass
class Warehouse:
    con: duckdb.DuckDBPyConnection
    tables: dict[str, dict] = field(default_factory=dict)   # name -> {rows, source, program}
    columns: list[Column] = field(default_factory=list)
    dictionary: Dictionary | None = None
    programs: dict[str, dict] = field(default_factory=dict)  # id -> {label, description, tables, rows, columns}
    _slots: threading.BoundedSemaphore = field(
        default_factory=lambda: threading.BoundedSemaphore(max(1, config.MAX_CONCURRENT_QUERIES)), repr=False)

    def execute(self, sql: str, params: list | None = None, max_rows: int | None = None,
                timeout: float | None = None) -> tuple[list[str], list[tuple]]:
        """Run one statement for a request. Every query a tool makes goes through here — Claude's SQL, the
        portfolio calculator, column profiling — so all of them get the same deadline and share the same
        bounded number of slots. Returns (column names, rows); raises QueryTimeout / QueryBusy."""
        timeout = config.QUERY_TIMEOUT_SECONDS if timeout is None else timeout
        if not self._slots.acquire(timeout=timeout):
            raise QueryBusy(f"The data engine is busy ({config.MAX_CONCURRENT_QUERIES} queries already running). "
                            f"Try again in a moment.")
        try:
            cur = self.con.cursor()
            timer = threading.Timer(timeout, cur.interrupt)
            timer.start()
            try:
                cur.execute(sql, params or [])
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall() if max_rows is None else cur.fetchmany(max_rows)
            except duckdb.InterruptException:
                raise QueryTimeout(f"Query exceeded {timeout:.0f}s and was stopped.") from None
            finally:
                timer.cancel()
            return cols, rows
        finally:
            self._slots.release()

    @classmethod
    def open(cls) -> "Warehouse":
        build_warehouse()
        con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
        if config.QUERY_MEMORY_LIMIT:
            con.execute(f"SET memory_limit = '{_setting(config.QUERY_MEMORY_LIMIT)}'")
        # Claude-written SQL must not read or write anything outside the warehouse.
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        wh = cls(con)
        wh.dictionary = Dictionary([Entry(*r) for r in con.execute(
            f"SELECT {', '.join(STD_FIELDS)} FROM _column_dictionary").fetchall()])
        dict_programs = {r[0] for r in con.execute("SELECT DISTINCT program FROM _column_dictionary").fetchall()}
        stats: dict[tuple[str, str], tuple[int, object]] = {}
        if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = '_column_stats'").fetchone()[0]:
            stats = {(t, c): (d, json.loads(v)) for t, c, d, v in con.execute("SELECT * FROM _column_stats").fetchall()}
        for tname, source, program in con.execute("SELECT table_name, source_file, program FROM _tables").fetchall():
            rows = con.execute(f'SELECT count(*) FROM "{tname}"').fetchone()[0]
            wh.tables[tname] = {"rows": rows, "source": source, "program": program}
            notes = _load_notes(program)
            for cname, dtype in con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position", [tname]).fetchall():
                linked = wh.dictionary.link(cname)
                # Cell-position links are only valid when the dictionary describes this program's workbook.
                if linked and linked[1] == "cell" and program not in dict_programs:
                    linked = None
                col = Column(tname, cname, dtype, *(linked or (None, None)))
                note = notes.get(cname)
                if note:
                    col.kind, col.note = note
                    col.link = col.link or "note"
                wh.columns.append(col)
            wh._annotate_constants(tname, stats)
        wh._build_programs()
        return wh

    def _build_programs(self) -> None:
        order = config.PROGRAM_KEYWORDS + ["DATA"]
        ids = sorted({i["program"] for i in self.tables.values()}, key=lambda p: order.index(p) if p in order else 99)
        for pid in ids:
            tbls = [t for t, i in self.tables.items() if i["program"] == pid]
            info = config.PROGRAM_INFO.get(pid, {"label": pid.title(), "description": ""})
            self.programs[pid] = {
                "id": pid, "label": info["label"], "description": info["description"], "tables": tbls,
                "rows": sum(self.tables[t]["rows"] for t in tbls),
                "columns": sum(1 for c in self.columns if c.table in tbls),
                "sources": [self.tables[t]["source"] for t in tbls],
            }

    def tables_for(self, program: str | None) -> list[str]:
        if not program:
            return list(self.tables)
        return self.programs.get(program, {}).get("tables", [])

    def _annotate_constants(self, tname: str, stats: dict[tuple[str, str], tuple[int, object]]) -> None:
        """Flag columns that are blank or hold one value in every row (model parameters etc.). Uses the profile
        stored at build time; a warehouse built before that existed is profiled here instead."""
        cols = [c for c in self.columns if c.table == tname]
        if not all((tname, c.name) in stats for c in cols):
            stats = {(tname, n): (d, v) for n, d, v in _column_stats(self.con, tname, [c.name for c in cols])}
        for c in cols:
            c.distinct, constant = stats[(tname, c.name)]
            if c.distinct == 1:
                c.constant = constant

    # ---- schema text for the system prompt ------------------------------
    def schema_summary(self, program: str | None = None, max_chars: int = 90_000) -> str:
        parts = []
        for tname in self.tables_for(program):
            info = self.tables[tname]
            cols = [c for c in self.columns if c.table == tname]
            parts.append(f'## Table "{tname}"  (from {info["source"]}: {info["rows"]:,} rows, {len(cols):,} columns)')
            labels = [c for c in cols if c.kind == "label"]
            cols = [c for c in cols if c.kind != "label"]
            full = [f"- {c.name} :: {_describe(c)}" for c in cols]
            if labels:
                full.append("- Worksheet label/header cells (hold a caption or a year, NOT data — ignore them; "
                            "they exist only because the extract copied every cell): "
                            + "; ".join(repr(c.name) for c in labels))
            if sum(len(x) for x in full) <= max_chars:
                parts.append("Columns as  name :: type. '= value' marks a column with the same value in every row; "
                             "'(all blank)' marks an empty column.")
                parts.extend(full)
            else:
                parts.append("This table is very wide, so related columns are grouped into families below. A family "
                             "line shows the shared name, how many columns it has and the variants (cohort, year, "
                             "cell). Use search_columns to get exact column names before writing SQL. "
                             "'= value' marks a column with the same value in every row.")
                parts.extend(_grouped_listing(cols))
            parts.append("")
        return "\n".join(parts)

    # ---- tools ----------------------------------------------------------
    def search_columns(self, keywords: str, table: str | None = None, limit: int = 25,
                       program: str | None = None) -> dict:
        terms = [t for t in re.split(r"[^0-9a-zA-Z%$&]+", keywords.lower()) if t]
        if not terms:
            return {"error": "Give one or more keywords."}
        allowed = set(self.tables_for(program))
        scored = []
        for c in self.columns:
            if table and c.table != table:
                continue
            if c.table not in allowed:
                continue
            name = c.name.lower()
            is_label = c.kind == "label"
            if is_label and name != keywords.strip().lower():
                continue
            desc = f"{c.entry.definition} {c.entry.notes} {c.entry.header}".lower() if c.entry else ""
            if c.note:
                desc += " " + c.note.lower()
            score = sum(3 if t in name else 1 if t in desc else 0 for t in terms)
            matched = sum(1 for t in terms if t in name or t in desc)
            if matched:
                scored.append((0 if is_label else matched, score, -len(c.name), c))   # label cells rank last
        scored.sort(key=lambda x: x[:3], reverse=True)
        out = []
        for _, _, _, c in scored[:limit]:
            item = {"table": c.table, "column": c.name, "type": _short_type(c.dtype)}
            if c.note:
                item["note"] = c.note
                if c.kind:
                    item["kind"] = c.kind
            if c.entry:
                d = c.entry.as_dict()
                if c.link == "pattern" and d["dictionary_header"] != c.name:
                    d["note"] = ("Linked by field pattern: this definition is written for the dictionary header's "
                                 "cohort/year and applies the same way to this column's cohort/year.")
                item["dictionary"] = d
            item.update(self._profile(c))
            out.append(item)
        result = {"matches": out, "total_matches": len(scored)}
        if self.dictionary and self.dictionary.entries:
            linked = {c.entry.header for _, _, _, c in scored[:limit] if c.entry}
            refs = self.dictionary.search(terms, limit=6, exclude=linked)
            if refs:
                result["related_dictionary_entries"] = refs
                result["dictionary_note"] = ("Definitions from the column dictionary that match the keywords but are "
                                             "not linked to a specific data column. Use them to explain concepts; "
                                             "the header wording may differ from this table's column names.")
        return result

    def _profile(self, c: Column) -> dict:
        q = f'"{c.name}"'
        t = f'"{c.table}"'
        try:
            if _short_type(c.dtype) in ("number", "integer"):
                r = self.execute(f"SELECT count({q}), min({q}), max({q}), avg({q}) FROM {t}")[1][0]
                return {"non_null": r[0], "min": _clean(r[1]), "max": _clean(r[2]), "mean": _clean(r[3])}
            r = self.execute(f"SELECT count({q}), count(DISTINCT {q}) FROM {t}")[1][0]
            top = self.execute(f"SELECT {q}, count(*) n FROM {t} WHERE {q} IS NOT NULL "
                               f"GROUP BY 1 ORDER BY n DESC LIMIT 5")[1]
            return {"non_null": r[0], "distinct": r[1],
                    "top_values": [f"{_clean(v)} ({n})" for v, n in top]}
        except Exception as e:  # pragma: no cover - profiling is best-effort
            return {"profile_error": str(e)[:200]}

    def query(self, sql: str, max_rows: int, program: str | None = None, max_chars: int | None = None) -> dict:
        """Run one read-only SELECT. Returns columns, rows (capped by count and, with max_chars, by JSON size),
        row_count. With `program`, tables that belong to another program's dataset are refused."""
        sql = sql.strip().rstrip(";").strip()
        try:
            stmts = self.con.extract_statements(sql)
        except Exception as e:
            return {"error": f"SQL parse error: {e}"}
        if len(stmts) != 1 or stmts[0].type != duckdb.StatementType.SELECT:
            return {"error": "Only a single SELECT (or WITH … SELECT) statement is allowed."}
        cur = self.con.cursor()
        if program:
            try:
                used = {t.lower() for t in cur.get_table_names(sql)}
            except Exception:   # the query itself will report the problem
                used = set()
            other = sorted(t for t in used if t in self.tables and self.tables[t]["program"] != program)
            if other:
                return {"error": f"This chat is scoped to the {program} dataset. Table(s) {', '.join(other)} belong to "
                                 f"another dataset: the user can start a new chat for it, and compare_programs gives "
                                 f"a side-by-side view of the same TINs when it is available."}
        try:
            cols, rows = self.execute(sql, max_rows=max_rows + 1)
        except QueryTimeout as e:
            return {"error": f"{e} Simplify it."}
        except Exception as e:
            return {"error": str(e)[:1500]}
        truncated = len(rows) > max_rows
        rows = [[_cell(v) for v in r] for r in rows[:max_rows]]
        out = {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated}
        if max_chars is not None:
            kept = fit_rows(rows, max_chars - len(json.dumps(cols)))   # the column names count too
            if rows and not kept:
                return {"error": f"The result is too wide to return ({len(cols):,} columns). Select only the columns "
                                 f"you need."}
            if len(kept) < len(rows):
                out.update(rows=kept, row_count=len(kept), truncated=True,
                           note=f"Only the first {len(kept)} rows are included because the result was too large. "
                                f"Select fewer columns or aggregate.")
        return out


def _load_notes(program: str) -> dict[str, tuple[str, str]]:
    """Curated column notes for a program: data/column_notes-<program>.csv (falls back to column_notes.csv).
    Rows are 'column,kind,definition'; a column value starting with ^ is a regex applied to every column name.
    Returns {column_name: (kind, definition)} resolved lazily through a dict subclass."""
    for name in (f"column_notes-{program.lower()}.csv", "column_notes.csv"):
        path = config.DATA_DIR / name
        if path.exists():
            break
    else:
        return {}
    exact: dict[str, tuple[str, str]] = {}
    patterns: list[tuple[re.Pattern, tuple[str, str]]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            col, kind, definition = (row.get("column") or "").strip(), (row.get("kind") or "metric").strip(), (row.get("definition") or "").strip()
            if not col or not definition:
                continue
            if col.startswith("^"):
                try:
                    patterns.append((re.compile(col), (kind, definition)))
                except re.error:
                    log.warning("Bad regex in %s: %s", path.name, col)
            else:
                exact[col] = (kind, definition)

    class Notes(dict):
        def get(self, key, default=None):
            if key in exact:
                return exact[key]
            for rx, val in patterns:
                if rx.search(key):
                    return val
            return default

    log.info("  column notes for %s: %d exact, %d patterns", program, len(exact), len(patterns))
    return Notes()


_VARIANT_RE = re.compile(r"\s*(\[[^\]]*\]|\((?:[A-Za-z ]+ )?[A-Z]{1,3}\d+\))\s*$")
_CLAIMS_RE = re.compile(r"^(?P<year>20\d\d) (?P<rest>.*? claims - )(?P<cohort>.+?) (?P<cat>[A-Za-z/ -]+?) (?P<kind>paid|claims cost) (?P<unit>.+)$")


def _family_key(name: str) -> tuple[str, str]:
    """Split a column name into (family, variant). Variants are trailing [..] / (cell) parts and, for
    ' — ' / ' | ' separated names, everything after the first separator."""
    m = _CLAIMS_RE.match(name)
    if m:  # "2025 MSSP claims - Aged dual SNF paid PMPM" → family per year/unit, variant cohort+category
        return f"{m['year']} {m['rest']}<cohort> <category> {m['kind']} {m['unit']}", f"{m['cohort']} {m['cat']}"
    variants = []
    base = name
    while True:
        m = _VARIANT_RE.search(base)
        if not m:
            break
        variants.insert(0, m.group(1))
        base = base[:m.start()]
    for sep in (" — ", " | "):
        if sep in base:
            head, tail = base.split(sep, 1)
            # keep the sheet prefix ("MSSP Parameters — X") as part of the family; the tail is the field
            if sep == " — ":
                sub = _family_key(tail)
                return f"{head} — {sub[0]}", " ".join(x for x in (sub[1], *variants) if x)
            variants.insert(0, tail)
            base = head
            break
    return base.strip(), " ".join(variants).strip()


def _grouped_listing(cols: list[Column]) -> list[str]:
    groups: dict[str, list[tuple[str, Column]]] = {}
    order: list[str] = []
    for c in cols:
        fam, var = _family_key(c.name)
        if fam not in groups:
            groups[fam] = []
            order.append(fam)
        groups[fam].append((var, c))
    out = []
    for fam in order:
        members = groups[fam]
        if len(members) == 1:
            c = members[0][1]
            out.append(f"- {c.name} :: {_describe(c)}")
            continue
        types = {_short_type(c.dtype) for _, c in members}
        consts = {repr(c.constant) for _, c in members if c.distinct == 1}
        const = ""
        if len(consts) == 1 and all(c.distinct == 1 for _, c in members):
            const = f" = {members[0][1].constant!r}"
        variants = [v for v, _ in members if v]
        shown = ", ".join(variants[:8]) + (f", … (+{len(variants) - 8} more)" if len(variants) > 8 else "")
        out.append(f"- {fam} :: {'/'.join(sorted(types))}{const}  [{len(members)} columns: {shown}]")
    return out


def _describe(c: Column) -> str:
    t = _short_type(c.dtype)
    if c.distinct == 0:
        out = f"{t} (all blank)"
    elif c.distinct == 1:
        v = c.constant
        v = f"'{v}'" if isinstance(v, str) else v
        out = f"{t} = {v}"
    else:
        out = t
    if c.note and c.kind in ("duplicate", "raw", "parameter"):
        n = c.note if len(c.note) <= 110 else c.note[:107] + "…"
        out += f"  — {n}"
    return out


def _short_type(dtype: str) -> str:
    d = dtype.upper()
    if d in ("DOUBLE", "FLOAT", "REAL") or d.startswith("DECIMAL"):
        return "number"
    if "INT" in d:
        return "integer"
    if d in ("BOOLEAN",):
        return "boolean"
    if "DATE" in d or "TIME" in d:
        return "date"
    return "text"


def fit_rows(rows: list, max_chars: int) -> list:
    """The leading rows whose JSON fits in max_chars."""
    used = 0
    for i, r in enumerate(rows):
        used += len(json.dumps(r, default=str)) + 2
        if used > max_chars:
            return rows[:i]
    return rows


def _cell(v):
    """A query result value: JSON-safe, with very long text cut."""
    v = _clean(v)
    if isinstance(v, str) and len(v) > config.MAX_CELL_CHARS:
        return v[:config.MAX_CELL_CHARS] + "…"
    return v


def _clean(v):
    """Make values JSON-safe and compact."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(f"{v:.8g}")
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v
