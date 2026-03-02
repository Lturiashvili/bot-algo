"""
V2.7 Signal Pressure Analyzer
--------------------------------
Non-invasive diagnostics helper.

Usage (inside orderbook_alpha after computing flags):

from pressure_analyzer import log_pressure

log_pressure(
    symbol=symbol,
    up15=up15,
    up30=up30,
    up1h=up1h,
    rsi_ok=rsi_ok,
    not_too_extended=not_too_extended,
    rsi_val=float(r15.iloc[-1]),
    dist=float(dist),
)

This does NOT change trading logic — only logs structured diagnostics.
"""

import logging
from collections import defaultdict

log = logging.getLogger("pressure")

# in-memory counters (safe for single-process worker)
_pressure_counts = defaultdict(int)
_total_checks = defaultdict(int)


def log_pressure(
    *,
    symbol: str,
    up15: bool,
    up30: bool,
    up1h: bool,
    rsi_ok: bool,
    not_too_extended: bool,
    rsi_val: float,
    dist: float,
) -> None:
    """Log per-tick pressure and accumulate statistics."""

    # ---- per-event diagnostic ----
    log.info(
        "pressure_check | %s | trend15=%s trend30=%s trend1h=%s rsi_ok=%s ext_ok=%s rsi=%.2f dist=%.4f",
        symbol,
        up15,
        up30,
        up1h,
        rsi_ok,
        not_too_extended,
        rsi_val,
        dist,
    )

    # ---- accumulate failure stats ----
    _total_checks[symbol] += 1

    if not up15:
        _pressure_counts[(symbol, "trend15")] += 1
    if not up30:
        _pressure_counts[(symbol, "trend30")] += 1
    if not up1h:
        _pressure_counts[(symbol, "trend1h")] += 1
    if not rsi_ok:
        _pressure_counts[(symbol, "rsi")] += 1
    if not not_too_extended:
        _pressure_counts[(symbol, "extension")] += 1


def dump_pressure_summary() -> None:
    """Call occasionally to see dominant bottlenecks."""
    for symbol in sorted(_total_checks):
        total = _total_checks[symbol]
        if total == 0:
            continue

        log.info("pressure_summary | %s | samples=%d", symbol, total)

        for key in ("trend15", "trend30", "trend1h", "rsi", "extension"):
            fails = _pressure_counts.get((symbol, key), 0)
            pct = (fails / total) * 100.0
            log.info(
                "pressure_summary | %s | %s_fail=%.1f%% (%d/%d)",
                symbol,
                key,
                pct,
                fails,
                total,
            )
