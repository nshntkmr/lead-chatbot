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
Headroom against a target: h = target × benchmark $ − expense $; a set meets the target
exactly when Σh ≥ 0, which is what makes "which TINs fix / fit my MLR" a simple sort.
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
    params: dict = field(default_factory=dict)

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
                "sharing_rule": "LEAD Global corridors: 0–15% of benchmark kept 100%, 15–35% 50%, 35–50% 25%, "
                                "beyond 50% 10%; 2% sequestration on the shared amount."}

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


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _n(name: str) -> str:
    """Quoted column cast to DOUBLE (workbook cells may hold '-' placeholders as text)."""
    return f"TRY_CAST({_q(name)} AS DOUBLE)"


def build_spec(wh: Warehouse, program: str) -> ProgramSpec | None:
    """Pick the spec that matches the program's table by looking at its columns."""
    tables = wh.tables_for(program)
    if not tables:
        return None
    table = tables[0]
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
            cohorts=cohorts, extra_sums=extras, params=params,
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
    exp_usd: float

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
        rows = self.wh.con.cursor().execute(sql, params).fetchall()
        return [Row(str(r[0]), str(r[1]), r[2] or "", str(r[3] or ""), float(r[4] or 0), float(r[5] or 0),
                    float(r[6] or 0), float(r[7] or 0)) for r in rows]

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
        v = self.wh.con.cursor().execute(
            f'SELECT sum({expr}) FROM "{self.spec.table}" WHERE {self.spec.tin} IN ({", ".join("?" * len(tins))})',
            tins).fetchone()[0]
        return float(v or 0)

    # --------------------------------------------------------------- metrics
    def metrics(self, tins: list[str], target_mlr: float | None = None,
                expense_change_pct: float = 0.0, benchmark_change_pct: float = 0.0) -> dict:
        rows, unknown = self.fetch(tins)
        valid = [r for r in rows if r.bm_usd > 0]
        zero = [r.tin for r in rows if r.bm_usd <= 0]
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
        npis: dict[str, list[str]] = {}
        for r in valid:
            npis.setdefault(r.npi, []).append(r.tin)
        dup = {n: t for n, t in npis.items() if len(t) > 1}
        if dup:
            warnings.append("TINs sharing one NPI (their source population overlaps, so the combined figures "
                            "double-count it): " + "; ".join(f"NPI {n}: {', '.join(t)}" for n, t in dup.items()))
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
        for label, expr in self.spec.extra_sums.items():
            combined[label] = round(self._sum(expr, ids))
        if "enhanced_pcc_repayment_usd" in combined:
            combined["total_monies_owed_usd"] = round(combined["net_shared_savings_usd"] + combined["enhanced_pcc_repayment_usd"])
        out = {
            "program": self.program,
            "tin_count": len(valid),
            "combined": combined,
            "tins": [
                {"tin": r.tin, "organization": r.org, self._cls_key(): r.cls, "person_years": round(r.py, 1),
                 "benchmark_usd": round(r.bm_usd), "expense_usd": round(r.exp_usd), "gross_margin_usd": round(r.margin),
                 "mlr": round(r.mlr, 4) if r.mlr is not None else None,
                 **({"headroom_usd_at_target": round(r.headroom(target_mlr))} if target_mlr else {})}
                for r in valid],
            "warnings": warnings,
        }
        if target_mlr and bm > 0:
            slack = sum(r.headroom(target_mlr) for r in valid)
            out["target"] = {
                "target_mlr": target_mlr, "meets_target": slack >= 0, "slack_usd": round(slack),
                "meaning": ("Positive slack: expense can rise by this much (or benchmark fall) before the combined MLR "
                            "exceeds the target. Negative: expense must fall by this much to reach it."),
            }
        if expense_change_pct or benchmark_change_pct:
            out["stress_test"] = {"expense_change_pct": expense_change_pct, "benchmark_change_pct": benchmark_change_pct,
                                  "note": "All figures are AFTER applying these changes to every TIN. Call again "
                                          "without them for the base case."}
        out["cohorts"] = self._cohorts(ids)
        if out["cohorts"]:
            cb = sum(c["benchmark_usd"] for c in out["cohorts"]); ce = sum(c["expense_usd"] for c in out["cohorts"])
            out["cohort_note"] = (f"Cohort benchmarks and expenses are on the same basis as the combined figures (after discount "
                                  f"and quality) and sum to ${cb:,.0f} / ${ce:,.0f} vs combined ${combined['benchmark_usd']:,.0f} / "
                                  f"${combined['expense_usd']:,.0f}.")
        return out

    def _cls_key(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.spec.cls_header.lower()).strip("_")

    def _cohorts(self, tins: list[str]) -> list[dict]:
        if not tins or not self.spec.cohorts:
            return []
        parts = [f"sum({py}), sum({bm}), sum({ex})" for _, py, bm, ex in self.spec.cohorts]
        r = self.wh.con.cursor().execute(
            f'SELECT {", ".join(parts)} FROM "{self.spec.table}" WHERE {self.spec.tin} IN ({", ".join("?" * len(tins))})',
            tins).fetchone()
        out = []
        for i, (name, *_rest) in enumerate(self.spec.cohorts):
            py, bm, ex = (float(x or 0) for x in r[3 * i: 3 * i + 3])
            out.append({"cohort": name, "person_years": round(py, 1), "benchmark_usd": round(bm), "expense_usd": round(ex),
                        "gross_margin_usd": round(bm - ex), "mlr": round(ex / bm, 4) if bm > 0 else None})
        return out

    # --------------------------------------------------------------- suggest
    def suggest(self, current: list[str], target_mlr: float, exclude: list[str] | None = None,
                name_like: str | None = None, class_like: str | None = None,
                min_person_years: float | None = None, max_person_years: float | None = None,
                limit: int = 25) -> dict:
        cur_rows, unknown = self.fetch(current)
        cur_rows = [r for r in cur_rows if r.bm_usd > 0]
        slack = sum(r.headroom(target_mlr) for r in cur_rows)
        bm_cur = sum(r.bm_usd for r in cur_rows)
        ex_cur = sum(r.exp_usd for r in cur_rows)
        out: dict = {
            "program": self.program,
            "target_mlr": target_mlr,
            "current": {"tin_count": len(cur_rows), "benchmark_usd": round(bm_cur),
                        "mlr": round(ex_cur / bm_cur, 4) if bm_cur else None, "slack_usd": round(slack),
                        "meets_target": slack >= 0},
            "warnings": [f"{len(unknown)} TIN(s) not in the {self.program} data: {', '.join(unknown[:20])}"] if unknown else [],
        }

        if cur_rows and slack < 0:
            if all(r.headroom(target_mlr) < 0 for r in cur_rows):
                best = min(cur_rows, key=lambda r: r.mlr)
                out["remove_to_reach_target"] = {
                    "possible": False,
                    "note": f"No subset of the current TINs meets the target: every TIN is individually above it. "
                            f"The lowest is {best.tin} ({best.org}) at MLR {best.mlr:.4f}.",
                }
            else:
                removed, running = [], slack
                for r in sorted(cur_rows, key=lambda r: r.headroom(target_mlr)):
                    if running >= 0:
                        break
                    running -= r.headroom(target_mlr)
                    removed.append({"tin": r.tin, "organization": r.org, "mlr": round(r.mlr, 4),
                                    "benchmark_usd": round(r.bm_usd), "headroom_usd": round(r.headroom(target_mlr)),
                                    "mlr_after_removal": round(self._mlr_without(cur_rows, [x["tin"] for x in removed] + [r.tin]), 4)})
                out["remove_to_reach_target"] = {"possible": True,
                                                 "note": "Fewest TINs to drop (largest MLR drag first) so the rest meet the target.",
                                                 "tins": removed}

        exclude_set = set(current) | set(exclude or [])
        where, params = [f"{self.spec.bm_usd} > 0"], []
        if exclude_set:
            where.append(f'{self.spec.tin} NOT IN ({", ".join("?" * len(exclude_set))})')
            params += list(exclude_set)
        if name_like:
            where.append(f"{self.spec.org} ILIKE ?")
            params.append(f"%{name_like}%")
        if class_like and self.spec.cls != "''":
            where.append(f"{self.spec.cls} ILIKE ?")
            params.append(f"%{class_like}%")
        if min_person_years is not None:
            where.append(f"{self.spec.py} >= ?")
            params.append(min_person_years)
        if max_person_years is not None:
            where.append(f"{self.spec.py} <= ?")
            params.append(max_person_years)
        cands = self._select(" AND ".join(where), params)
        fits_alone = [r for r in cands if r.headroom(target_mlr) >= 0]
        fits_with_slack = [r for r in cands if -slack <= r.headroom(target_mlr) < 0] if slack > 0 else []

        def fmt(r: Row, extra: dict | None = None):
            d = {"tin": r.tin, "organization": r.org, self._cls_key(): r.cls, "person_years": round(r.py, 1),
                 "benchmark_usd": round(r.bm_usd), "gross_margin_usd": round(r.margin), "mlr": round(r.mlr, 4),
                 "headroom_usd": round(r.headroom(target_mlr))}
            d.update(extra or {})
            return d

        out["candidates"] = {
            "screened": len(cands),
            "with_mlr_at_or_below_target": len(fits_alone),
            "largest_by_benchmark": [fmt(r) for r in sorted(fits_alone, key=lambda r: -r.bm_usd)[:limit]],
            "largest_by_margin": [fmt(r) for r in sorted(fits_alone, key=lambda r: -r.margin)[:limit]],
            "note": ("TINs with MLR at or below the target can be added in any combination without breaking it. "
                     "headroom_usd is target × benchmark − expense; a set meets the target when the sum of "
                     "headroom (current + added) is ≥ 0."),
        }
        if slack > 0 and fits_with_slack:
            out["candidates"]["above_target_but_fit_within_current_slack"] = {
                "count": len(fits_with_slack),
                "note": "Individually above the target, but small enough that adding ONE of them keeps the combined MLR "
                        "within target. Adding several uses up slack: their headroom must sum to ≥ −slack.",
                "largest_by_benchmark": [fmt(r) for r in sorted(fits_with_slack, key=lambda r: -r.bm_usd)[:limit]],
            }
        if slack < 0:
            plan, running, bm_run, ex_run = [], slack, bm_cur, ex_cur
            for r in sorted(fits_alone, key=lambda r: -r.headroom(target_mlr)):
                if running >= 0:
                    break
                running += r.headroom(target_mlr)
                bm_run += r.bm_usd
                ex_run += r.exp_usd
                plan.append(fmt(r, {"combined_mlr_after_adding": round(ex_run / bm_run, 4)}))
            out["add_to_reach_target"] = {
                "reached": running >= 0,
                "tins_needed": len(plan),
                "combined_mlr_after_all_additions": round(ex_run / bm_run, 4) if bm_run else None,
                "note": "Fewest TINs to add (largest headroom first) that bring the combined MLR to the target. "
                        "Other combinations work too if their headroom sums to at least the deficit."
                        + ("" if len(plan) <= limit else f" Only the first {limit} of {len(plan)} are listed."),
                "deficit_usd": round(-slack),
                "tins": plan[:limit],
            }
        return out

    @staticmethod
    def _mlr_without(rows: list[Row], drop: list[str]) -> float:
        keep = [r for r in rows if r.tin not in drop]
        bm = sum(r.bm_usd for r in keep)
        return sum(r.exp_usd for r in keep) / bm if bm else 0.0


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
