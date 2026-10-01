"""Token prices (USD per million tokens) and cost estimation.

Defaults are Anthropic list prices (platform.claude.com/docs/en/about-claude/pricing). Claude in Microsoft
Foundry bills the same USD rates converted to Claude Consumption Units, so the estimate matches Azure billing
before any negotiated discount; a US Data Zone deployment is 1.1× (set PRICE_MULTIPLIER=1.1).
Override or add models in data/pricing.json:  {"my-deployment-name": {"input": 4, "output": 20, "cache_write": 5, "cache_read": 0.2}}
Keys are matched as substrings of the model / deployment name, longest key first.
"""
from __future__ import annotations

import json
import logging

from . import config

log = logging.getLogger(__name__)

# (input, output, 5-minute cache write, cache read) — USD per million tokens
DEFAULT_RATES: dict[str, tuple[float, float, float, float]] = {
    "fable-5-1": (10, 50, 12.5, 0.25), "mythos-5-1": (10, 50, 12.5, 0.25),
    "fable-5": (10, 50, 12.5, 1.0), "mythos-5": (10, 50, 12.5, 1.0),
    "opus-5-5": (4, 20, 5, 0.20),
    "opus-5": (5, 25, 6.25, 0.50), "opus-4-8": (5, 25, 6.25, 0.50), "opus-4-7": (5, 25, 6.25, 0.50),
    "opus-4-6": (5, 25, 6.25, 0.50), "opus-4-5": (5, 25, 6.25, 0.50),
    "opus-4-1": (15, 75, 18.75, 1.50), "opus-4": (15, 75, 18.75, 1.50),
    "sonnet-5-5": (2, 10, 2.5, 0.20), "sonnet-5": (2, 10, 2.5, 0.20),
    "sonnet-4-6": (3, 15, 3.75, 0.30), "sonnet-4-5": (3, 15, 3.75, 0.30), "sonnet-4": (3, 15, 3.75, 0.30),
    "haiku-4-5": (1, 5, 1.25, 0.10), "haiku-3-5": (0.8, 4, 1.0, 0.08),
}
KEYS = ("input", "output", "cache_write", "cache_read")


def _load_rates() -> dict[str, tuple[float, float, float, float]]:
    rates = dict(DEFAULT_RATES)
    f = config.DATA_DIR / "pricing.json"
    if f.exists():
        try:
            for name, r in json.loads(f.read_text(encoding="utf-8")).items():
                base = float(r.get("input", 0))
                rates[name.lower()] = (base, float(r.get("output", 0)),
                                       float(r.get("cache_write", base * 1.25)), float(r.get("cache_read", base * 0.1)))
            log.info("Loaded pricing overrides from %s", f.name)
        except Exception:
            log.exception("Could not read %s; using default rates", f.name)
    return rates


RATES = _load_rates()


def rate_for(model: str) -> tuple[str, tuple[float, float, float, float]] | None:
    m = (model or "").lower()
    for key in sorted(RATES, key=len, reverse=True):
        if key in m:
            return key, RATES[key]
    return None


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_write: int, cache_read: int) -> tuple[float, bool]:
    """Estimated cost in USD and whether a rate was found for the model."""
    found = rate_for(model)
    if not found:
        return 0.0, False
    p_in, p_out, p_cw, p_cr = found[1]
    usd = (input_tokens * p_in + output_tokens * p_out + cache_write * p_cw + cache_read * p_cr) / 1e6
    return usd * config.PRICE_MULTIPLIER, True


def rate_card(models: list[str]) -> list[dict]:
    out = []
    for m in dict.fromkeys(models):
        found = rate_for(m)
        row = {"model": m, "matched": found[0] if found else None, "multiplier": config.PRICE_MULTIPLIER}
        if found:
            row.update(dict(zip(KEYS, found[1])))
        out.append(row)
    return out
