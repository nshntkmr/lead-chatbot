"""Column dictionary: links data columns to their definitions.

The dictionary file comes from the same workbook family as the data, but its headers
use the workbook's own naming ("MSSP PROSP — … (B3)", "SAS Raw beneficiaries [2024 ESRD]",
"2026 MSSP claims - ESRD SNF paid PMPM"), while the LEAD extract uses shorter names
("PROSP__B3", "Raw beneficiaries [2024 HN]", "2026 HN SNF claims cost (PMPM)").
We link them three ways, most reliable first:

  exact     header text is identical
  cell      data column "<Sheet>__<Cell>" = dictionary entry for that sheet + cell
  pattern   same field once sheet prefixes, cohort (ESRD/HN/AD/…) and wording
            differences are normalized; the definition is written for the cohort/year
            in the dictionary header, and applies the same way to this column's cohort/year

Every entry also stays searchable by keyword, so Claude can read the definition of a
concept even when no column links to it directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

STD_FIELDS = ["header", "units", "definition", "notes", "sheet", "cell", "formula", "source_type"]


@dataclass
class Entry:
    header: str
    units: str = ""
    definition: str = ""
    notes: str = ""
    sheet: str = ""
    cell: str = ""
    formula: str = ""
    source_type: str = ""

    def as_dict(self, max_len: int = 400) -> dict:
        d = {"dictionary_header": self.header}
        for k in ("units", "definition", "notes", "formula"):
            v = getattr(self, k)
            if v:
                d[k] = v[:max_len]
        if self.sheet:
            d["workbook_location"] = f"{self.sheet}!{self.cell}" if self.cell else self.sheet
        return d


def standardize(df: pd.DataFrame) -> pd.DataFrame:
    """Map a dictionary file's columns onto STD_FIELDS (tolerant of naming)."""
    cols = {c.lower().strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return df[cols[n]].fillna("").astype(str).str.strip()
        return pd.Series([""] * len(df))

    return pd.DataFrame({
        "header": pick("header", "column", "column_name", "field", "name") if any(
            n in cols for n in ("header", "column", "column_name", "field", "name")) else df.iloc[:, 0].astype(str),
        "units": pick("units", "unit"),
        "definition": pick("definition", "description", "desc"),
        "notes": pick("notes", "note", "comments"),
        "sheet": pick("sheet", "tab"),
        "cell": pick("cell"),
        "formula": pick("original_formula", "formula"),
        "source_type": pick("source_type", "type"),
    })


_COHORT = r"\b(esrd|hn|ad|a&d|disabled|aged dual|aged nondual|aged non-dual|tin total|total)\b"


def _norm(s: str) -> str:
    s = s.lower()
    s = (s.replace("claims cost", "paid").replace("(usd, jan-may)", "usd")
          .replace("(usd, full year)", "usd").replace("(pmpm)", "pmpm"))
    s = re.sub(r"^(mssp|lead) [a-z ]+ — ", "", s)            # "MSSP Parameters — " sheet prefix
    s = re.sub(r"\((?:[a-z]+ )?[a-z]{1,3}\d+\)$", "", s)     # trailing "(B5)" / "(Assignable F3)"
    s = re.sub(r"\b(mssp|lead|sas|supplied|source|claims|tin)\b", " ", s)
    s = re.sub(_COHORT, " <c> ", s)
    s = re.sub(r"[^a-z0-9<>]+", " ", s)
    return " ".join(s.split())


class Dictionary:
    def __init__(self, entries: list[Entry]):
        self.entries = entries
        self.by_header = {e.header: e for e in entries}
        self.by_cell: dict[tuple[str, str], Entry] = {}
        self.by_norm: dict[str, Entry] = {}
        for e in entries:
            if e.sheet and e.cell:
                key = re.sub(r"^(mssp|lead)\s+", "", e.sheet.lower()).replace(" ", "_")
                self.by_cell.setdefault((key, e.cell.upper()), e)
            self.by_norm.setdefault(_norm(e.header), e)
        self._search_text = [
            (e, e.header.lower(), f"{e.definition} {e.notes} {e.units}".lower()) for e in entries]

    def link(self, column: str) -> tuple[Entry, str] | None:
        """Return (entry, how) for a data column, or None."""
        if column in self.by_header:
            return self.by_header[column], "exact"
        m = re.match(r"^(.+?)__([A-Z]{1,3}\d+)$", column)
        if m:
            e = self.by_cell.get((m.group(1).lower(), m.group(2)))
            if e:
                return e, "cell"
        e = self.by_norm.get(_norm(column))
        if e:
            return e, "pattern"
        return None

    def search(self, terms: list[str], limit: int = 6, exclude: set[str] = frozenset()) -> list[dict]:
        scored = []
        for e, head, body in self._search_text:
            if e.header in exclude:
                continue
            matched = sum(1 for t in terms if t in head or t in body)
            if not matched:
                continue
            score = sum(3 if t in head else 1 if t in body else 0 for t in terms)
            scored.append((matched, score, e))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [e.as_dict(300) for _, _, e in scored[:limit]]
