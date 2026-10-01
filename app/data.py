"""Data layer: loads every CSV / Excel file in DATA_DIR into a local DuckDB
warehouse and exposes safe, read-only helpers that Claude's tools call."""
from __future__ import annotations

import csv
import datetime as dt
import decimal
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


def _read_file(path: Path) -> dict[str, pd.DataFrame]:
    """Return {table_name: dataframe}. Excel files give one table per sheet."""
    text_dtype = {c: str for c in config.TEXT_COLUMNS}
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=text_dtype, low_memory=False)
        return {_table_name(path.stem): df}
    sheets = pd.read_excel(path, sheet_name=None, dtype=text_dtype)
    if len(sheets) == 1:
        return {_table_name(path.stem): next(iter(sheets.values()))}
    return {_table_name(path.stem, s): df for s, df in sheets.items() if not df.empty}


def _data_files() -> list[Path]:
    return sorted(p for p in config.DATA_DIR.iterdir()
                  if p.suffix.lower() in DATA_EXTS and not p.name.startswith("~$")
                  and not p.stem.lower().startswith("column_notes"))


def build_warehouse(force: bool = False) -> None:
    """(Re)build the DuckDB file when any source file is newer than it."""
    files = _data_files()
    if not files:
        raise RuntimeError(f"No CSV/Excel files found in {config.DATA_DIR}")
    wh = config.WAREHOUSE_PATH
    if not force and wh.exists() and wh.stat().st_mtime >= max(f.stat().st_mtime for f in files):
        return
    log.info("Building data warehouse from %d file(s)…", len(files))
    tmp = wh.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute("CREATE TABLE _column_dictionary (header VARCHAR, units VARCHAR, definition VARCHAR, notes VARCHAR, "
                    "sheet VARCHAR, cell VARCHAR, formula VARCHAR, source_type VARCHAR, program VARCHAR)")
        con.execute("CREATE TABLE _tables (table_name VARCHAR, source_file VARCHAR, program VARCHAR)")
        for f in files:
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
                program = detect_program(f.name)
                con.execute("INSERT INTO _tables VALUES (?, ?, ?)", [tname, f.name, program])
                log.info("  table %s [%s]: %d rows x %d cols", tname, program, len(df), len(df.columns))
    finally:
        con.close()
    wh.unlink(missing_ok=True)
    tmp.rename(wh)


# --------------------------------------------------------------------------
# Read-only access
# --------------------------------------------------------------------------
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

    @classmethod
    def open(cls) -> "Warehouse":
        build_warehouse()
        con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
        # Claude-written SQL must not read or write anything outside the warehouse.
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        wh = cls(con)
        wh.dictionary = Dictionary([Entry(*r) for r in con.execute(
            f"SELECT {', '.join(STD_FIELDS)} FROM _column_dictionary").fetchall()])
        dict_programs = {r[0] for r in con.execute("SELECT DISTINCT program FROM _column_dictionary").fetchall()}
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
            wh._annotate_constants(tname)
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

    def _annotate_constants(self, tname: str) -> None:
        """Flag columns that are blank or hold one value in every row (model parameters etc.)."""
        cols = [c for c in self.columns if c.table == tname]
        for i in range(0, len(cols), 500):
            chunk = cols[i:i + 500]
            exprs = ", ".join(f'count(DISTINCT "{c.name}"), any_value("{c.name}")' for c in chunk)
            r = self.con.execute(f'SELECT {exprs} FROM "{tname}"').fetchone()
            for j, c in enumerate(chunk):
                c.distinct = r[2 * j]
                if c.distinct == 1:
                    c.constant = _clean(r[2 * j + 1])

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
            cur = self.con.cursor()
            if _short_type(c.dtype) in ("number", "integer"):
                r = cur.execute(f"SELECT count({q}), min({q}), max({q}), avg({q}) FROM {t}").fetchone()
                return {"non_null": r[0], "min": _clean(r[1]), "max": _clean(r[2]), "mean": _clean(r[3])}
            r = cur.execute(f"SELECT count({q}), count(DISTINCT {q}) FROM {t}").fetchone()
            top = cur.execute(f"SELECT {q}, count(*) n FROM {t} WHERE {q} IS NOT NULL "
                              f"GROUP BY 1 ORDER BY n DESC LIMIT 5").fetchall()
            return {"non_null": r[0], "distinct": r[1],
                    "top_values": [f"{_clean(v)} ({n})" for v, n in top]}
        except Exception as e:  # pragma: no cover - profiling is best-effort
            return {"profile_error": str(e)[:200]}

    def query(self, sql: str, max_rows: int) -> dict:
        """Run one read-only SELECT. Returns columns, rows (capped), row_count."""
        sql = sql.strip().rstrip(";").strip()
        try:
            stmts = self.con.extract_statements(sql)
        except Exception as e:
            return {"error": f"SQL parse error: {e}"}
        if len(stmts) != 1 or stmts[0].type != duckdb.StatementType.SELECT:
            return {"error": "Only a single SELECT (or WITH … SELECT) statement is allowed."}
        cur = self.con.cursor()
        timer = threading.Timer(config.QUERY_TIMEOUT_SECONDS, cur.interrupt)
        timer.start()
        try:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
        except duckdb.InterruptException:
            return {"error": f"Query exceeded {config.QUERY_TIMEOUT_SECONDS:.0f}s and was stopped. Simplify it."}
        except Exception as e:
            return {"error": str(e)[:1500]}
        finally:
            timer.cancel()
        truncated = len(rows) > max_rows
        rows = [[_clean(v) for v in r] for r in rows[:max_rows]]
        return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated}


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
