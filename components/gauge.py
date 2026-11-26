"""Main gas-level display: a ring gauge with threshold markers (HTML + CSS)."""
from __future__ import annotations

from typing import Optional

import config
from components.common import ago, esc, num, render

def _step(pct: float) -> int:
    """Position on the ring in half-percent steps (0-200); CSS classes gg-p0 ... gg-p200 turn this into an angle."""
    return int(round(min(max(pct, 0.0), 100.0) * 2))


def gauge_ring(pct: Optional[float], settings) -> str:
    """The ring gauge, drawn with plain HTML + CSS (conic-gradient). No inline SVG: some Streamlit versions
    strip <svg> from st.html, which left this card without its ring."""
    value = 0.0 if pct is None else min(max(pct, 0.0), 100.0)
    empty = " gg-arc-empty" if value < 0.3 else ""
    at = f"gg-p{_step(value)}"

    ticks = "".join(
        f'<i class="gg-tick{" gg-tick-major" if step % 25 == 0 else ""} gg-p{step * 2}"></i>'
        for step in range(0, 100, 5)  # 100% overlaps 0%
    )
    marks = "".join(
        f'<i class="{css} gg-p{_step(threshold)}"></i>'
        for threshold, css in ((settings.low_pct, "gg-mark gg-mark-warn"), (settings.critical_pct, "gg-mark gg-mark-crit"))
    )
    shown = "--" if pct is None else f"{value:.1f}"
    return (
        '<div class="gg-ring" role="img" aria-label="Gas level gauge">'
        '<i class="gg-ring-track"></i>'
        f'<i class="gg-ring-glow {at}{empty}"></i>'
        f'<i class="gg-ring-arc {at}{empty}"></i>'
        f'<i class="gg-ring-dot gg-p0{empty}"></i><i class="gg-ring-dot {at}{empty}"></i>'
        + ticks
        + marks
        + f'<div class="gg-ring-center"><div class="gg-ring-pct">{shown}<span class="gg-ring-sign">%</span></div>'
        '<div class="gg-ring-cap">REMAINING</div></div>'
        "</div>"
    )


def build_gauge_html(gas, settings, mode: str, latest_ts: Optional[str], source_label: str) -> str:
    tag = ""
    updated = f"UPDATED {ago(latest_ts).upper()}" if latest_ts else "NO READING YET"
    return f"""
    <div class="gg-card gg-gauge-card gg-tone-{esc(gas.tone)}">
      <div class="gg-card-head">
        <span class="gg-label">Gas level</span>
        <span>{tag}<span class="gg-status">{esc(gas.status)}</span></span>
      </div>
      <div class="gg-gauge-body">
        <div class="gg-gauge-wrap">{gauge_ring(gas.level_pct, settings)}</div>
        <div class="gg-gauge-stats">
          <div class="gg-stat"><span class="gg-label">Remaining LPG</span>
            <span class="gg-stat-val">{num(gas.remaining_kg)}<small>kg</small></span></div>
          <div class="gg-stat"><span class="gg-label">Cylinder weight</span>
            <span class="gg-stat-val">{num(gas.weight)}<small>kg</small></span></div>
          <div class="gg-stat"><span class="gg-label">Capacity</span>
            <span class="gg-stat-val">{settings.cylinder_capacity_kg:.1f}<small>kg</small></span></div>
          <div class="gg-stat"><span class="gg-label">Status</span>
            <span class="gg-stat-val">{esc(gas.status)}</span></div>
        </div>
      </div>
      <div class="gg-card-foot">{esc(config.MODES[mode]['label'])} &middot; {esc(updated)}</div>
    </div>
    """


def render_gauge(gas, settings, mode: str, latest_ts: Optional[str], source_label: str) -> None:
    render(build_gauge_html(gas, settings, mode, latest_ts, source_label))
