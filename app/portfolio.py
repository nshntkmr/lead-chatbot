"""Portfolio calculator: combined financials for a set of TINs, what-if changes, TIN
suggestions against an MLR target, and side-by-side program comparison.

Each program (LEAD, MSSP, …) gets a ProgramSpec that says which columns hold the
headline figures and how shared savings are computed. Both specs reproduce the
workbook's own identities, verified against the data:

  LEAD   benchmark $ = Benchmark PBPM (after discount & quality) × person-years × 12
         expense $   = Projected expense PBPM × person-years × 12
         sharing     = Global risk corridors on the combined margin (100/50/25/10 %)
  MSSP   benchmark $ = Projected benchmark (= benchmark per person-year × person-years)
         expense $   = Projected expenditures
         sharing     = ENHANCED: 75 % of savings when margin ≥ MSR, 40 % of losses when
                       margin ≤ −MLR (rates and MSR read from the workbook constants),
                       reported both as the workbook does (uncapped) and with the
                       ENHANCED caps (20 % savings / 15 % losses of benchmark)

Combined MLR is Σ expense $ ÷ Σ benchmark $, never an average of per-TIN MLRs.
Room under a target: h = target × benchmark $ − expense $; a set meets the target exactly
when Σh ≥ 0, which is what makes "which TINs fix / fit my MLR" a simple sort. (Output fields
use the wording the users read — room_under_target_usd — so answers need no translation.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .data import Warehouse

LEAD_CORRIDORS = [(0.15, 1.00), (0.35, 0.50), (0.50, 0.25), (float("inf"), 0.10)]   # Global risk option
SEQUESTRATION = 0.02


def corridor_share(margin: float, benchmark: float, corridors=LEAD_CORRIDORS) -> float:
    """Shared savings (+) or losses (−) after LEAD risk corridors."""
    if benchmark <= 0 or margin == 0:
        return 0.0
    pct = abs(margin) / benchmark
    shared, lower = 0.0, 0.0
    for upper, rate in corridors:
        if pct <= lower:
            break
        band = min(pct, upper) - lower
        shared += band * benchmark * rate
        lower = upper
    return shared if margin > 0 else -shared


def clean_tins(values) -> list[str]:
    if isinstance(values, (str, int)):
        values = [values]
    out, seen = [], set()
    for v in values or []:
        for t in re.split(r"[\s,;]+", str(v)):
            t = t.strip().replace("-", "")
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


# --------------------------------------------------------------------------
# Program specs
# --------------------------------------------------------------------------
@dataclass
class ProgramSpec:
    program: str
    table: str
    # SQL expressions (column names already quoted) for the headline fields
    tin: str
    npi: str
    org: str
    cls: str                 # a classification column shown per TIN ('' if none)
    cls_header: str
    py: str
    benes: str
    bm_usd: str
    exp_usd: str
    cohorts: list[tuple[str, str, str, str]]       # (name, person-years expr, benchmark $ expr, expense $ expr)
    extra_sums: dict[str, str] = field(default_factory=dict)   # label -> SQL expression summed over the TINs
    extra_distinct: dict[str, str] = field(default_factory=dict)   # label -> SQL expression; distinct values over the TINs
    params: dict = field(default_factory=dict)
    net_key: str = ""        # key in share() holding the net shared result
    per_tin: dict[str, str] = field(default_factory=dict)   # label -> SQL expression read per TIN (workbook base case)
    notes: str = ""          # SQL expression for the per-TIN source notes ('' if the extract has none)

    def net(self, margin: float, bm: float) -> float:
        """The net shared result at full precision (share() rounds each line for display)."""
        return self.share(margin, bm).get(self.net_key, 0)

    def pooling_note(self, rows: list, pooled: float, standalone: float) -> str:
        """Why the pooled result and the sum of standalone TIN results agree or differ."""
        return ""

    def share(self, margin: float, bm: float) -> dict:          # overridden per program
        raise NotImplementedError

    def worst_case(self, bm: float) -> float:
        raise NotImplementedError


class LeadSpec(ProgramSpec):
    def share(self, margin: float, bm: float) -> dict:
        shared = corridor_share(margin, bm)
        seq = -SEQUESTRATION * abs(shared)
        return {"shared_savings_after_global_corridors_usd": round(shared),
                "sequestration_usd": round(seq),
                "net_shared_savings_usd": round(shared + seq),
                "settlement_line_labels": {
                    "shared_savings_after_global_corridors_usd": "Shared savings after Global corridors (the workbook's "
                                                                 "'Settlement | shared savings or losses', before sequestration)",
                    "sequestration_usd": "Sequestration (2%)",
                    "net_shared_savings_usd": "Shared savings net of sequestration",
                    "enhanced_pcc_repayment_usd": "Enhanced PCC repayment",
                    "total_monies_owed_usd": "Projected net settlement"},
                "sharing_rule": "LEAD Global corridors: 0–15% of benchmark kept 100%, 15–35% 50%, 35–50% 25%, "
                                "beyond 50% 10%; 2% sequestration on the shared amount."}

    def net(self, margin: float, bm: float) -> float:
        shared = corridor_share(margin, bm)
        return shared - SEQUESTRATION * abs(shared)

    def pooling_note(self, rows: list, pooled: float, standalone: float) -> str:
        first = LEAD_CORRIDORS[0][0]
        outside = [r.tin for r in rows if abs(r.margin) > first * r.bm_usd]
        gains, losses = sum(r.margin > 0 for r in rows), sum(r.margin < 0 for r in rows)
        if not outside and not (gains and losses):
            return (f"Pooled and standalone agree for this portfolio because every TIN's "
                    f"{'savings' if gains else 'losses'} fall inside the first corridor (within {first:.0%} of its own "
                    f"benchmark, shared 100%) and each carries the same {SEQUESTRATION:.0%} sequestration. Give this as the "
                    "reason; 'all TINs show savings' alone is not sufficient. It does not carry over to other portfolios "
                    "or to a stress test.")
        why = []
        if gains and losses:
            why.append(f"{gains} TIN(s) show savings and {losses} show losses, which net against each other when pooled "
                       "while sequestration reduces each gain and deepens each loss when taken separately")
        if outside:
            bm = sum(r.bm_usd for r in rows)
            share = abs(sum(r.margin for r in rows)) / bm if bm else 0.0
            why.append(f"{len(outside)} TIN(s) go beyond the first corridor ({first:.0%} of their own benchmark) when taken "
                       f"separately ({_some(outside, 5)}), so part of their result is shared at the lower rates, while the "
                       f"pooled margin is {share:.1%} of the pooled benchmark, which puts a different amount into those "
                       "lower-rate bands")
        return f"Pooled and standalone differ by ${abs(pooled - standalone):,.0f} because " + "; and ".join(why) + "."

    def worst_case(self, bm: float) -> tuple[str, float, str]:
        return ("shared_loss_if_loss_equals_benchmark_usd", corridor_share(-bm, bm),
                "Illustrative scenario, not a cap: the shared loss if gross losses reached 100% of the benchmark "
                "(15%×100% + 20%×50% + 15%×25% + 50%×10% = 33.75% of benchmark). Losses beyond that keep sharing at 10%; "
                "the LEAD corridors have no absolute ceiling in this workbook.")


class MsspSpec(ProgramSpec):
    def share(self, margin: float, bm: float) -> dict:
        p = self.params
        msr, rate, loss_rate = p["msr"], p["sharing_rate"], p["loss_rate"]
        if bm <= 0:
            return {"shared_savings_or_losses_usd": 0, "status": "n/a"}
        if margin >= msr * bm:
            status, shared = "Saving", rate * margin
            capped = min(shared, p["savings_cap"] * bm)
        elif margin <= -msr * bm:
            status, shared = "Losses", loss_rate * margin
            capped = max(shared, -p["loss_cap"] * bm)
        else:
            status, shared, capped = "No shared savings or losses (inside the MSR/MLR band)", 0.0, 0.0
        return {"status": status,
                "msr_mlr_band_usd": round(msr * bm),
                "shared_savings_or_losses_usd": round(shared),
                "shared_after_enhanced_caps_usd": round(capped),
                "cap_binding": abs(capped - shared) > 1,
                "sharing_rule": (f"MSSP {p['track']}: savings shared at {rate:.0%} when margin ≥ MSR {msr:.1%} of "
                                 f"benchmark; losses shared at {loss_rate:.0%} when margin ≤ −{msr:.1%}. The workbook's "
                                 f"'original model' figure is uncapped; the capped figure applies the {p['savings_cap']:.0%} "
                                 f"savings / {p['loss_cap']:.0%} loss caps. Sequestration is not modeled in the workbook.")}

    def worst_case(self, bm: float) -> tuple[str, float, str]:
        return ("max_shared_loss_under_enhanced_cap_usd", -self.params["loss_cap"] * bm,
                f"Hard cap: ENHANCED shared losses cannot exceed {self.params['loss_cap']:.0%} of the benchmark.")


def _some(tins: list[str], n: int = 10) -> str:
    """A TIN list for a warning: the first n and a count of the rest."""
    return ", ".join(tins[:n]) + (f" and {len(tins) - n} more ({len(tins)} TINs)" if len(tins) > n else "")


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _n(name: str) -> str:
    """Quoted column cast to DOUBLE (workbook cells may hold '-' placeholders as text)."""
    return f"TRY_CAST({_q(name)} AS DOUBLE)"


class PortfolioUnavailable(RuntimeError):
    """The program's data cannot support portfolio math; the message says why and is shown to the user."""


def build_spec(wh: Warehouse, program: str) -> ProgramSpec | None:
    """The spec for the program's headline table. None when no table has the headline columns. Raises
    PortfolioUnavailable when the layout would make the totals wrong: more than one table with headline
    columns (the calculator reads exactly one, so the others' TINs would be silently left out) or a TIN on
    more than one row (every sum assumes one row per TIN)."""
    found = [s for s in (_spec_for(wh, program, t) for t in wh.tables_for(program)) if s]
    if not found:
        return None
    if len(found) > 1:
        raise PortfolioUnavailable(
            f"{len(found)} {program} tables hold headline figures ({', '.join(s.table for s in found)}). Portfolio "
            f"math reads one table per program: give the extract files the same header so they load as one table, "
            f"or remove the extra file.")
    spec = found[0]
    rows, tins = wh.execute(f'SELECT count(*), count(DISTINCT {spec.tin}) FROM "{spec.table}"')[1][0]
    if rows != tins:
        raise PortfolioUnavailable(
            f"{rows - tins:,} of the {rows:,} {program} rows repeat a TIN (or have none). Portfolio math needs one "
            f"row per TIN; fix the extract and rebuild.")
    return spec


def _spec_for(wh: Warehouse, program: str, table: str) -> ProgramSpec | None:
    """The spec that matches one table, judged by its columns."""
    have = {c.name for c in wh.columns if c.table == table}

    # ---- LEAD extract -------------------------------------------------------
    lead_needed = ["Benchmark PBPM after discount and earned quality", "Projected expense PBPM",
                   "Person years after exposure adjustment", "Total benchmark"]
    if all(c in have for c in lead_needed):
        py = _q("Person years after exposure adjustment")
        # Cohort benchmarks in the workbook are BEFORE the discount and quality withhold; scale them by the TIN's
        # (after discount & earned quality ÷ before discount) ratio so the cohorts sum to 'Total benchmark' and
        # cohort MLRs are on the same basis as the combined MLR.
        adj = (f'({_q("Benchmark PBPM after discount and earned quality")} / NULLIF({_q("Benchmark PBPM before discount")}, 0))')
        cohorts = []
        for name, k in (("Aged & Disabled", "AD"), ("High Needs", "HN"), ("ESRD", "ESRD")):
            cpy = _q(f"Person years by cohort | {k} | PY2027")
            cohorts.append((name, cpy, f'{_q(f"Updated benchmark PBPM | {k} | PY2027")} * {adj} * {cpy} * 12',
                            f'{_q(f"Projected expense PBPM | {k} | PY2027")} * {cpy} * 12'))
        return LeadSpec(
            program=program, table=table, tin=_q("TIN"), npi=_q("NPI"), org=_q("Organization"),
            cls=_q("ACO spending classification") if "ACO spending classification" in have else "''",
            cls_header="Spending class", py=py, benes=_q("Total cohort beneficiaries | 2026"),
            bm_usd=_q("Total benchmark"), exp_usd=f'{_q("Projected expense PBPM")} * {py} * 12',
            cohorts=cohorts,
            extra_sums={
                "enhanced_pcc_repayment_usd": _q("Settlement | enhanced PCC repayment"),
                "financial_guarantee_usd": _q("Financial guarantee amount"),
                "quality_withhold_at_risk_usd": f'{_q("Quality withhold PBPM")} * {py} * 12',
            },
            extra_distinct={"benchmark_discount_rates_applied": _q("Benchmark discount")} if "Benchmark discount" in have else {},
            net_key="net_shared_savings_usd",
            per_tin=({"projected_net_settlement_usd": _q("Settlement | total monies owed")}
                     if "Settlement | total monies owed" in have else {}),
            notes=_q("Input notes") if "Input notes" in have else "",
            params={"note": "Each TIN's benchmark carries its own High/Low-Spending classification (discount 1.75% vs "
                            "3%, regional adjustment). A real ACO gets one classification for the whole population."},
        )

    # ---- MSSP extract -------------------------------------------------------
    mssp_needed = ["Projected benchmark", "Projected expenditures", "Projected person years", "Pre-sharing MLR"]
    if all(c in have for c in mssp_needed):
        def const(col: str, default):
            if col not in have:
                return default
            v = next((c.constant for c in wh.columns if c.table == table and c.name == col), None)
            try:
                return float(v) if v not in (None, "", "-") else default
            except (TypeError, ValueError):
                return default
        track_col = next((c for c in wh.columns if c.table == table and c.name == "MSSP track"), None)
        params = {
            "track": track_col.constant if track_col and track_col.constant else "ENHANCED",
            "msr": abs(const("MSSP Shared Saving Losses — Minimum Savings Rate (%) [PY2027] (B26)", 0.005)),
            "sharing_rate": const("MSSP Shared Saving Losses — Final Sharing Rate (%) [PY2027] (B36)", 0.75),
            "loss_rate": abs(const("MSSP Shared Saving Losses — Shared Loss Rate (%) [PY2027] (B37)", 0.40)),
            "savings_cap": const("MSSP Inputs by Track — Shared Savings Cap (Row [X] in Table 3) [ENHANCED Track] (G8)", 0.20),
            "loss_cap": 0.15,
        }
        cohorts = []
        for name, k, c_py, c_bm, c_ex in (("ESRD", "ESRD", "C15", "D35", "B10"), ("Disabled", "Disabled", "C16", "D36", "B11"),
                                          ("Aged / dual", "Aged/dual", "C17", "D37", "B12"),
                                          ("Aged / non-dual", "Aged/non-dual", "C18", "D38", "B13")):
            cpy = _n(f"MSSP Shared Saving Losses — Projected cohort person years — {k} [PY2027] ({c_py})")
            bm = _n(f"MSSP Updated Benchmark — Updated Benchmark Expenditures ($) — {k} [PY2027] ({c_bm})")
            ex = _n(f"MSSP Shared Saving Losses — Projected expense — {k} [PY2027] ({c_ex})")
            cohorts.append((name, cpy, f"{bm} * {cpy}", f"{ex} * {cpy}"))
        extras = {}
        if "MSSP Shared Saving Losses — Financial guarantee (B47)" in have:
            extras["financial_guarantee_usd"] = _n("MSSP Shared Saving Losses — Financial guarantee (B47)")
        if "MSSP Health Equity Adj — Health Equity Benchmark Adjustment ($) [Health equity adjustment] (C11)" in have:
            extras["health_equity_adjustment_usd"] = (
                f'{_n("MSSP Health Equity Adj — Health Equity Benchmark Adjustment ($) [Health equity adjustment] (C11)")}'
                f' * {_n("Projected person years")}')
        return MsspSpec(
            program=program, table=table, tin=_q("TIN"), npi=_q("NPI"), org=_q("Organization"),
            cls=_q("MSSP Shared Saving Losses — Savings or Losses Realized [PY2027] (B30)")
            if "MSSP Shared Saving Losses — Savings or Losses Realized [PY2027] (B30)" in have else "''",
            cls_header="Workbook result", py=_q("Projected person years"), benes=_q("Projected beneficiaries"),
            bm_usd=_q("Projected benchmark"), exp_usd=_q("Projected expenditures"),
            cohorts=cohorts, extra_sums=extras, params=params, net_key="shared_savings_or_losses_usd",
        )
    return None


# --------------------------------------------------------------------------
# Calculator
# --------------------------------------------------------------------------
@dataclass
class Row:
    tin: str
    npi: str
    org: str
    cls: str
    py: float
    benes: float
    bm_usd: float
    exp_usd: float | None    # None = blank in the workbook (not zero cost); such rows are excluded, never summed

    @property
    def margin(self) -> float:
        return self.bm_usd - self.exp_usd

    @property
    def mlr(self) -> float | None:
        return self.exp_usd / self.bm_usd if self.bm_usd > 0 else None

    def headroom(self, target: float) -> float:
        return target * self.bm_usd - self.exp_usd


class PortfolioCalc:
    def __init__(self, wh: Warehouse, spec: ProgramSpec):
        self.wh = wh
        self.spec = spec

    @property
    def program(self) -> str:
        return self.spec.program

    # ------------------------------------------------------------------ data
    def _select(self, where: str, params: list) -> list[Row]:
        s = self.spec
        sql = (f"SELECT {s.tin}, {s.npi}, {s.org}, {s.cls}, {s.py}, {s.benes}, {s.bm_usd}, {s.exp_usd} "
               f'FROM "{s.table}" WHERE {where}')
        return [_row(r) for r in self.wh.execute(sql, params)[1]]

    @staticmethod
    def _usable(rows: list[Row]) -> tuple[list[Row], list[str], list[str]]:
        """(rows with a benchmark and an expense, TINs with a zero benchmark, TINs with a benchmark but no expense)."""
        return ([r for r in rows if r.bm_usd > 0 and r.exp_usd is not None],
                [r.tin for r in rows if r.bm_usd <= 0],
                [r.tin for r in rows if r.bm_usd > 0 and r.exp_usd is None])

    def fetch(self, tins: list[str]) -> tuple[list[Row], list[str]]:
        if not tins:
            return [], []
        rows = self._select(f'{self.spec.tin} IN ({", ".join("?" * len(tins))})', tins)
        found = {r.tin for r in rows}
        order = {t: i for i, t in enumerate(tins)}
        rows.sort(key=lambda r: order.get(r.tin, 1e9))
        return rows, [t for t in tins if t not in found]

    def _sum(self, expr: str, tins: list[str]) -> float:
        if not tins:
            return 0.0
        v = self.wh.execute(
            f'SELECT sum({expr}) FROM "{self.spec.table}" WHERE {self.spec.tin} IN ({", ".join("?" * len(tins))})',
            tins)[1][0][0]
        return float(v or 0)

    # --------------------------------------------------------------- metrics
    def metrics(self, tins: list[str], target_mlr: float | None = None,
                expense_change_pct: float = 0.0, benchmark_change_pct: float = 0.0) -> dict:
        rows, unknown = self.fetch(tins)
        valid, zero, no_expense = self._usable(rows)
        if expense_change_pct or benchmark_change_pct:   # stress test: scale every TIN, keep the identities
            for r in valid:
                r.exp_usd *= 1 + expense_change_pct / 100
                r.bm_usd *= 1 + benchmark_change_pct / 100
        bm = sum(r.bm_usd for r in valid)
        ex = sum(r.exp_usd for r in valid)
        py = sum(r.py for r in valid)
        margin = bm - ex
        mlr = ex / bm if bm > 0 else None
        warnings = []
        if unknown:
            warnings.append(f"{len(unknown)} TIN(s) not in the {self.program} data: {', '.join(unknown[:20])}")
        if zero:
            warnings.append(f"{len(zero)} TIN(s) have a zero benchmark in the workbook and were excluded: {', '.join(zero[:20])}")
        if no_expense:
            warnings.append(f"{len(no_expense)} TIN(s) have a benchmark but no projected expense in the workbook and were "
                            f"excluded (a blank is not zero cost): {', '.join(no_expense[:20])}")
        npis: dict[str, list[str]] = {}
        for r in valid:
            npis.setdefault(r.npi, []).append(r.tin)
        dup = {n: t for n, t in npis.items() if len(t) > 1}
        if dup:
            warnings.append("TINs sharing one NPI (their source population overlaps, so the combined figures "
                            "double-count it): " + "; ".join(f"NPI {n}: {_some(t)}" for n, t in list(dup.items())[:20])
                            + (f"; and {len(dup) - 20} more NPIs" if len(dup) > 20 else ""))
        if isinstance(self.spec, LeadSpec) and len({r.cls for r in valid}) > 1:
            warnings.append("Mix of High- and Low-Spending TINs. " + self.spec.params["note"] +
                            " The combined figure is therefore an approximation.")
        ids = [r.tin for r in valid]
        combined = {
            "program": self.program,
            "person_years": round(py, 1),
            "beneficiaries": round(sum(r.benes for r in valid), 1),
            "benchmark_usd": round(bm),
            "expense_usd": round(ex),
            "gross_margin_usd": round(margin),
            "mlr": round(mlr, 4) if mlr is not None else None,
            "savings_pct_of_benchmark": round(margin / bm, 4) if bm > 0 else None,
            "benchmark_per_person_year": round(bm / py, 2) if py else None,
            "expense_per_person_year": round(ex / py, 2) if py else None,
            "benchmark_pbpm": round(bm / py / 12, 2) if py else None,
            "expense_pbpm": round(ex / py / 12, 2) if py else None,
            **self.spec.share(margin, bm),
        }
        if bm:
            wc_key, wc_val, wc_note = self.spec.worst_case(bm)
            combined[wc_key] = round(wc_val)
            combined[wc_key.replace("_usd", "_note")] = wc_note
        nk = self.spec.net_key
        if nk and nk in combined and len(valid) > 1:
            # Sharing rules are not linear, so one pooled ACO differs from the sum of standalone TIN results.
            pooled = self.spec.net(margin, bm)
            standalone = sum(self.spec.net(r.margin, r.bm_usd) for r in valid)   # summed unrounded, rounded once
            combined["sum_of_standalone_tin_results_usd"] = round(standalone)
            combined["settlement_method_note"] = (
                f"{nk} applies the sharing rules once to the pooled margin of all the TINs, as one ACO. "
                "sum_of_standalone_tin_results_usd applies them to each TIN separately and adds the results (what summing "
                "the workbook's per-TIN column gives). Report the pooled figure and say it is pooled: it is a modeling "
                "assumption, not a CMS consolidated calculation.")
            note = self.spec.pooling_note(valid, pooled, standalone)
            if note:
                combined["pooled_vs_standalone_note"] = note
        for label, expr in self.spec.extra_sums.items():
            combined[label] = round(self._sum(expr, ids))
        for label, expr in self.spec.extra_distinct.items():
            combined[label] = self._distinct(expr, ids)
        if "enhanced_pcc_repayment_usd" in combined:
            combined["total_monies_owed_usd"] = round(combined["net_shared_savings_usd"] + combined["enhanced_pcc_repayment_usd"])
        # Per-TIN workbook figures are base case, so they are left out of a stress test.
        per_tin = {} if expense_change_pct or benchmark_change_pct else self._per_tin(ids)
        for label in self.spec.per_tin if per_tin else ():
            vals = [per_tin[t][label] for t in ids if per_tin.get(t, {}).get(label) is not None]
            combined[f"sum_of_tin_{label}"] = round(sum(vals))
            combined[f"{label.removesuffix('_usd')}_by_tin_note"] = (
                f"Each TIN's standalone figure from the workbook, shown per TIN in the user's table: "
                f"{sum(v > 0 for v in vals)} TIN(s) positive (projected to be paid to the ACO), "
                f"{sum(v < 0 for v in vals)} negative (projected to be owed to CMS). Say this split in one line.")
        overlap = self._overlap(ids, bool(dup))
        if overlap.get("warning"):
            warnings.append(overlap.pop("warning"))
        out = {
            "program": self.program,
            "tin_count": len(valid),
            "combined": combined,
            "tins": [
                {"tin": r.tin, "organization": r.org, self._cls_key(): r.cls, "person_years": round(r.py, 1),
                 "benchmark_usd": round(r.bm_usd), "expense_usd": round(r.exp_usd), "gross_margin_usd": round(r.margin),
                 "mlr": round(r.mlr, 4) if r.mlr is not None else None,
                 **{k: round(v) for k, v in per_tin.get(r.tin, {}).items() if v is not None},
                 **({"room_under_target_usd": round(r.headroom(target_mlr))} if target_mlr else {})}
                for r in valid],
            "warnings": warnings,
            **overlap,
        }
        if target_mlr and bm > 0:
            room = sum(r.headroom(target_mlr) for r in valid)
            out["target"] = {
                "target_mlr": target_mlr, "meets_target": room >= 0, "room_under_target_usd": round(room),
                "meaning": ("Positive: room under the target — expense can rise by this much (or benchmark fall) before "
                            "the combined MLR exceeds the target. Negative: the spending reduction needed to reach it."),
            }
        if expense_change_pct or benchmark_change_pct:
            out["stress_test"] = {"expense_change_pct": expense_change_pct, "benchmark_change_pct": benchmark_change_pct,
                                  "note": "Benchmark, expense, margin, MLR, sharing, per-TIN rows and cohorts are AFTER "
                                          "applying these changes to every TIN. Sums read from the workbook (enhanced PCC "
                                          "repayment, financial guarantee, quality withhold, other adjustments) stay at "
                                          "their base-case values. Call again without the changes for the base case."}
        out["cohorts"] = self._cohorts(ids, target_mlr, 1 + expense_change_pct / 100, 1 + benchmark_change_pct / 100)
        if out["cohorts"]:
            cb = sum(c["benchmark_usd"] for c in out["cohorts"]); ce = sum(c["expense_usd"] for c in out["cohorts"])
            basis = " (after discount and quality)" if isinstance(self.spec, LeadSpec) else ""
            out["cohort_note"] = (f"Cohort benchmarks and expenses are on the same basis as the combined figures{basis} "
                                  f"and sum to ${cb:,.0f} / ${ce:,.0f} vs combined ${combined['benchmark_usd']:,.0f} / "
                                  f"${combined['expense_usd']:,.0f}."
                                  + (" Cohort benchmarks are derived, not workbook columns: each TIN's benchmark discount is "
                                     "allocated to its cohorts pro rata. Say so when you report them."
                                     if isinstance(self.spec, LeadSpec) else "")
                                  + (" room_under_target_usd is target × cohort benchmark − cohort expense; the cohort values "
                                     "sum to the portfolio's room_under_target_usd, so a negative value is that cohort's "
                                     "contribution to the target gap." if target_mlr else ""))
        return out

    def _per_tin(self, tins: list[str]) -> dict[str, dict]:
        """{tin: {label: value}} for the spec's per-TIN workbook columns."""
        if not tins or not self.spec.per_tin:
            return {}
        labels = list(self.spec.per_tin)
        rows = self.wh.execute(
            f'SELECT {self.spec.tin}, {", ".join(self.spec.per_tin[k] for k in labels)} FROM "{self.spec.table}" '
            f'WHERE {self.spec.tin} IN ({", ".join("?" * len(tins))})', tins)[1]
        return {str(r[0]): {k: (float(v) if v is not None else None) for k, v in zip(labels, r[1:])} for r in rows}

    def _overlap(self, tins: list[str], shared_npi: bool) -> dict:
        """What the source notes say about TINs whose NPI data also map to other selection keys, in the words the
        answer should use. Distinct NPIs and absent keys rule out the flagged double-counting, nothing more."""
        if not tins or not self.spec.notes:
            return {}
        s = self.spec
        rows = self.wh.execute(
            f'SELECT {s.tin}, {s.notes} FROM "{s.table}" WHERE {s.tin} IN ({", ".join("?" * len(tins))}) '
            f"AND {s.notes} ILIKE '%selection keys%'", tins)[1]
        other: dict[str, list[str]] = {}
        for tin, note in rows:
            m = re.search(r"selection keys\s+([\d,\s]+)", str(note))
            keys = [k for k in clean_tins(m.group(1)) if k != str(tin)] if m else []
            if keys:
                other[str(tin)] = keys
        if not other:
            return {}
        have = set(tins)
        both = {t: [k for k in ks if k in have] for t, ks in other.items()}
        both = {t: ks for t, ks in both.items() if ks}
        all_keys = sorted({k for ks in other.values() for k in ks})
        checked = len(all_keys) <= 1000
        in_file = {str(r[0]) for r in self.wh.execute(
            f'SELECT {s.tin} FROM "{s.table}" WHERE {s.tin} IN ({", ".join("?" * len(all_keys))})', all_keys)[1]} if checked else set()
        eg = "; ".join(f"{t} also maps to {', '.join(ks)}" for t, ks in list(other.items())[:10])
        out = {"alternative_selection_keys": [{"tin": t, "other_keys": ks} for t, ks in list(other.items())[:20]]}
        if both:
            out["warning"] = ("TINs that the source notes say map to the same organization-level NPI data are both in this "
                              "portfolio, so the combined figures double-count that population: "
                              + "; ".join(f"{t} with {', '.join(ks)}" for t, ks in list(both.items())[:20]))
            where = "Some of those keys are in this portfolio (see warnings). "
        elif in_file:
            where = (f"None of those other keys is in this portfolio; {len(in_file)} of them exist as TIN rows in this file "
                     "and should not be added alongside. ")
        elif checked:
            where = "None of those other keys is in this portfolio, and none of them is a TIN row in this file. "
        else:
            where = "None of those other keys is in this portfolio. "
        out["population_overlap_note"] = (
            f"Source notes for {len(other)} of the {len(tins)} TINs say their organization-level NPI data also map to "
            f"other selection keys ({eg}{'; …' if len(other) > 10 else ''}), which must not be added as independent "
            "populations. " + where
            + ("" if shared_npi else "The TINs in this portfolio have distinct NPIs. ")
            + "The file does not establish whether beneficiary populations overlap between the TINs. State the caveat in "
              "these terms: do not write that there is no overlap or no double-counting.")
        return out

    def _cls_key(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.spec.cls_header.lower()).strip("_")

    def _distinct(self, expr: str, tins: list[str]) -> list:
        if not tins:
            return []
        rows = self.wh.execute(
            f'SELECT DISTINCT {expr} FROM "{self.spec.table}" WHERE {self.spec.tin} IN ({", ".join("?" * len(tins))}) ORDER BY 1',
            tins)[1]
        return [r[0] for r in rows if r[0] is not None]

    def _cohorts(self, tins: list[str], target_mlr: float | None = None,
                 expense_factor: float = 1.0, benchmark_factor: float = 1.0) -> list[dict]:
        if not tins or not self.spec.cohorts:
            return []
        parts = [f"sum({py}), sum({bm}), sum({ex})" for _, py, bm, ex in self.spec.cohorts]
        r = self.wh.execute(
            f'SELECT {", ".join(parts)} FROM "{self.spec.table}" WHERE {self.spec.tin} IN ({", ".join("?" * len(tins))})',
            tins)[1][0]
        out = []
        for i, (name, *_rest) in enumerate(self.spec.cohorts):
            py, bm, ex = (float(x or 0) for x in r[3 * i: 3 * i + 3])
            bm, ex = bm * benchmark_factor, ex * expense_factor   # stress test: same scaling as the TIN rows
            out.append({"cohort": name, "person_years": round(py, 1), "benchmark_usd": round(bm), "expense_usd": round(ex),
                        "gross_margin_usd": round(bm - ex), "mlr": round(ex / bm, 4) if bm > 0 else None,
                        **({"room_under_target_usd": round(target_mlr * bm - ex)} if target_mlr else {})})
        return out

    # --------------------------------------------------------------- suggest
    def suggest(self, current: list[str], target_mlr: float, exclude: list[str] | None = None,
                name_like: str | None = None, class_like: str | None = None,
                min_person_years: float | None = None, max_person_years: float | None = None,
                limit: int = 25, candidates: list[str] | None = None) -> dict:
        cur_rows, unknown = self.fetch(current)
        cur_rows, _, no_expense = self._usable(cur_rows)
        room = sum(r.headroom(target_mlr) for r in cur_rows)
        bm_cur = sum(r.bm_usd for r in cur_rows)
        ex_cur = sum(r.exp_usd for r in cur_rows)
        out: dict = {
            "program": self.program,
            "target_mlr": target_mlr,
            "current": {"tin_count": len(cur_rows), "benchmark_usd": round(bm_cur),
                        "mlr": round(ex_cur / bm_cur, 4) if bm_cur else None, "room_under_target_usd": round(room),
                        "meets_target": room >= 0},
            "warnings": [f"{len(unknown)} TIN(s) not in the {self.program} data: {', '.join(unknown[:20])}"] if unknown else [],
        }
        if no_expense:
            out["warnings"].append(f"{len(no_expense)} TIN(s) have a benchmark but no projected expense in the workbook "
                                   f"and were left out: {', '.join(no_expense[:20])}")

        if cur_rows and room < 0:
            if all(r.headroom(target_mlr) < 0 for r in cur_rows):
                best = min(cur_rows, key=lambda r: r.mlr)
                out["remove_to_reach_target"] = {
                    "possible": False,
                    "note": f"No subset of the current TINs meets the target: every TIN is individually above it. "
                            f"The lowest is {best.tin} ({best.org}) at MLR {best.mlr:.4f}.",
                }
            else:
                removed, running, bm_left, ex_left = [], room, bm_cur, ex_cur
                for r in sorted(cur_rows, key=lambda r: r.headroom(target_mlr)):
                    if running >= 0:
                        break
                    running -= r.headroom(target_mlr)
                    bm_left -= r.bm_usd
                    ex_left -= r.exp_usd
                    removed.append({"tin": r.tin, "organization": r.org, "mlr": round(r.mlr, 4),
                                    "benchmark_usd": round(r.bm_usd), "room_under_target_usd": round(r.headroom(target_mlr)),
                                    "mlr_after_removal": round(ex_left / bm_left, 4) if bm_left > 0 else 0.0})
                out["remove_to_reach_target"] = {
                    "possible": True,
                    "note": "Fewest TINs to drop (largest contribution to the target gap first) so the rest meet the target."
                            + ("" if len(removed) <= limit else f" Only the first {limit} of {len(removed)} are listed."),
                    "tins_to_remove": len(removed), "tins": removed[:limit]}

        # Candidates are screened, ranked and cut to `limit` in SQL, so only the rows that are shown leave the database.
        # Ties keep file order (rowid).
        s = self.spec
        exclude_set = set(current) | set(exclude or [])
        where, params = [f"{s.bm_usd} > 0", f"({s.exp_usd}) IS NOT NULL"], []
        if exclude_set:
            where.append(f'{s.tin} NOT IN ({", ".join("?" * len(exclude_set))})')
            params += list(exclude_set)
        if candidates:   # a pool screened elsewhere (any column, via SQL); the room maths still runs here
            pool = [t for t in dict.fromkeys(candidates) if t not in exclude_set]
            where.append(f'{s.tin} IN ({", ".join("?" * len(pool))})' if pool else "FALSE")
            params += pool
        if name_like:
            where.append(f"{s.org} ILIKE ?")
            params.append(f"%{name_like}%")
        if class_like and s.cls != "''":
            where.append(f"{s.cls} ILIKE ?")
            params.append(f"%{class_like}%")
        if min_person_years is not None:
            where.append(f"{s.py} >= ?")
            params.append(min_person_years)
        if max_person_years is not None:
            where.append(f"{s.py} <= ?")
            params.append(max_person_years)
        cte = (f"WITH c AS (SELECT {s.tin} AS tin, {s.npi} AS npi, {s.org} AS org, {s.cls} AS cls, {s.py} AS py, "
               f"{s.benes} AS benes, CAST({s.bm_usd} AS DOUBLE) AS bm, CAST({s.exp_usd} AS DOUBLE) AS ex, rowid AS rid "
               f'FROM "{s.table}" WHERE {" AND ".join(where)}), '
               f"h AS (SELECT *, ? * bm - ex AS room FROM c) ")
        base = params + [target_mlr]
        cols = "tin, npi, org, cls, py, benes, bm, ex"

        def run(tail: str, extra: list | None = None) -> list:
            return self.wh.execute(cte + tail, base + (extra or []))[1]

        def fmt(r: Row, extra: dict | None = None):
            d = {"tin": r.tin, "organization": r.org, self._cls_key(): r.cls, "person_years": round(r.py, 1),
                 "benchmark_usd": round(r.bm_usd), "gross_margin_usd": round(r.margin), "mlr": round(r.mlr, 4),
                 "room_under_target_usd": round(r.headroom(target_mlr))}
            d.update(extra or {})
            return d

        def top(cond: str, order: str, extra: list | None = None) -> list[Row]:
            return [_row(r) for r in run(f"SELECT {cols} FROM h WHERE {cond} ORDER BY {order}, rid LIMIT ?",
                                         (extra or []) + [limit])]

        # "Fits within the current room": individually above the target, by no more than the portfolio's room.
        screened, fits_alone, fits_within_room = run(
            "SELECT count(*), count(*) FILTER (WHERE room >= 0), count(*) FILTER (WHERE room < 0 AND room >= ?) FROM h",
            [-room])[0]
        out["candidates"] = {
            "screened": screened,
            "with_mlr_at_or_below_target": fits_alone,
            "largest_by_benchmark": [fmt(r) for r in top("room >= 0", "bm DESC")],
            "largest_by_margin": [fmt(r) for r in top("room >= 0", "bm - ex DESC")],
            "note": (("TINs with MLR at or below the target can be added in any combination without breaking it. "
                      if room >= 0 else
                      "The current TINs are above the target, so adding a TIN with MLR at or below it lowers the combined "
                      "MLR but does not by itself reach the target: that needs enough of them (see add_to_reach_target). "
                      "Do not say any combination of them meets the target. ")
                     + "room_under_target_usd is target × benchmark − expense; a set meets the target when it sums "
                       "(current + added) to ≥ 0."),
        }
        if candidates:
            out["candidates"]["pool_note"] = (
                f"Candidates were limited to the {len(dict.fromkeys(candidates))} TINs supplied; {screened} of them are "
                "outside the current portfolio and have a benchmark and an expense. Say what the pool was screened on.")
        if room > 0 and fits_within_room:
            out["candidates"]["above_target_but_fit_within_current_room"] = {
                "count": fits_within_room,
                "note": "Individually above the target, but small enough that adding ONE of them keeps the combined MLR "
                        "within target. Adding several uses up the room: their room_under_target_usd must sum to at "
                        "least minus the portfolio's.",
                "largest_by_benchmark": [fmt(r) for r in top("room < 0 AND room >= ?", "bm DESC", [-room])],
            }
        if room < 0:
            # Largest room first; a TIN is needed while the room added before it is still short of the gap.
            over = "OVER (ORDER BY room DESC, rid ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"
            plan_cte = (f", f AS (SELECT *, sum(room) {over} AS cum_room, sum(bm) {over} AS cum_bm, sum(ex) {over} AS cum_ex, "
                        f"row_number() OVER (ORDER BY room DESC, rid) AS rn FROM h WHERE room >= 0), "
                        f"p AS (SELECT * FROM f WHERE cum_room - room < ?) ")
            gap = -room
            n, added_room, added_bm, added_ex = run(
                plan_cte + "SELECT count(*), arg_max(cum_room, rn), arg_max(cum_bm, rn), arg_max(cum_ex, rn) FROM p", [gap])[0]
            plan = [fmt(_row(r), {"combined_mlr_after_adding": round((ex_cur + r[9]) / (bm_cur + r[8]), 4)})
                    for r in run(plan_cte + f"SELECT {cols}, cum_bm, cum_ex FROM p ORDER BY rn LIMIT ?", [gap, limit])]
            bm_run, ex_run = bm_cur + (added_bm or 0), ex_cur + (added_ex or 0)
            out["add_to_reach_target"] = {
                "reached": room + (added_room or 0) >= 0,
                "tins_needed": n,
                "combined_mlr_after_all_additions": round(ex_run / bm_run, 4) if bm_run else None,
                "note": "Fewest TINs to add (most room under the target first) that bring the combined MLR to the target. "
                        "Other combinations work too if their room under the target sums to at least the shortfall."
                        + ("" if n <= limit else f" Only the first {limit} of {n} are listed."),
                "shortfall_to_target_usd": round(gap),
                "tins": plan,
            }
        return out


def _row(r) -> Row:
    return Row(str(r[0]), str(r[1]), r[2] or "", str(r[3] or ""), float(r[4] or 0), float(r[5] or 0),
               float(r[6] or 0), None if r[7] is None else float(r[7]))


def compare_programs(calcs: dict[str, PortfolioCalc], tins: list[str]) -> dict:
    """Headline figures for the same TINs under every program that has a calculator."""
    out = {"tins_requested": tins, "programs": {}, "per_tin": []}
    per: dict[str, dict] = {}
    for pid, calc in calcs.items():
        m = calc.metrics(tins)
        c = m["combined"]
        shared = c.get("net_shared_savings_usd", c.get("shared_after_enhanced_caps_usd", c.get("shared_savings_or_losses_usd")))
        out["programs"][pid] = {
            "tins_found": m["tin_count"], "person_years": c["person_years"], "benchmark_usd": c["benchmark_usd"],
            "expense_usd": c["expense_usd"], "gross_margin_usd": c["gross_margin_usd"], "mlr": c["mlr"],
            "shared_result_usd": shared,
            "shared_result_basis": ("LEAD: after Global corridors and sequestration" if pid == "LEAD" and "net_shared_savings_usd" in c
                                    else "MSSP: with ENHANCED caps applied" if "shared_after_enhanced_caps_usd" in c else "workbook"),
            "warnings": m["warnings"],
        }
        for t in m["tins"]:
            per.setdefault(t["tin"], {"tin": t["tin"], "organization": t["organization"]})[pid] = {
                "person_years": t["person_years"], "benchmark_usd": t["benchmark_usd"],
                "gross_margin_usd": t["gross_margin_usd"], "mlr": t["mlr"]}
    out["per_tin"] = list(per.values())
    out["note"] = ("The two workbooks model different programs with different benchmark rules, cohorts and sharing "
                   "formulas, and may project different populations for the same TIN, so compare margins and MLR rather "
                   "than raw person-years.")
    return out
