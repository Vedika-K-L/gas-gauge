"""Spotlight stat tiles above the analytics charts, computed from the selected time window."""
from __future__ import annotations

from typing import Optional

from components.common import esc, num, render


def _tile(label: str, value: str, unit: str, note: str, tone: str = "ok") -> str:
    return (
        f'<div class="gg-card gg-stat-tile gg-tone-{esc(tone)}">'
        f'<span class="gg-label">{esc(label)}</span>'
        f'<div class="gg-value"><span class="gg-num">{esc(value)}</span><span class="gg-unit">{esc(unit)}</span></div>'
        f'<div class="gg-sub">{esc(note)}</div></div>'
    )


def build_stats_html(view, settings, range_label: str, live: bool) -> str:
    """`view` is the enriched history for the chosen window (columns ts, weight, level_pct)."""
    level = view["level_pct"].dropna() if (view is not None and "level_pct" in view) else None
    weight = view["weight"].dropna() if (view is not None and "weight" in view) else None
    have = level is not None and len(level) > 0

    avg: Optional[float] = float(level.mean()) if have else None
    low: Optional[float] = float(level.min()) if have else None
    used: Optional[float] = float(weight.iloc[0] - weight.iloc[-1]) if weight is not None and len(weight) > 1 else None
    count = 0 if view is None else len(view)

    def tone(v: Optional[float]) -> str:
        if v is None:
            return "ok"
        if v <= settings.critical_pct:
            return "crit"
        return "warn" if v <= settings.low_pct else "ok"

    pill = (
        f'<span class="gg-pill" style="--tone:var({"--lime" if live else "--muted"})">'
        f'<span class="gg-dot"></span>{"LIVE" if live else "OFFLINE"}</span>'
    )
    used_txt = "—" if used is None else f"{max(used, 0):.2f}" if used >= 0 else f"+{-used:.2f}"
    used_note = "net change in window" if used is None or used >= 0 else "net gain (refill)"
    tiles = (
        _tile("Average level", num(avg, 1), "%", f"over {range_label}", tone(avg))
        + _tile("Lowest level", num(low, 1), "%", "minimum in window", tone(low))
        + _tile("Gas used", used_txt, "kg", used_note)
        + _tile("Readings", f"{count:,}", "", "stored samples")
    )
    return (
        f'<div class="gg-livebar"><span class="gg-label">Live analytics &middot; {esc(range_label)}</span>{pill}</div>'
        f'<div class="gg-stats">{tiles}</div>'
    )


def render_live_stats(view, settings, range_label: str, live: bool) -> None:
    render(build_stats_html(view, settings, range_label, live))
