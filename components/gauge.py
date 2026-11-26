"""Main gas-level display: a custom SVG ring gauge with threshold markers."""
from __future__ import annotations

import math
from typing import Optional

import config
from components.common import ago, esc, num, render

_RADIUS = 94
_CIRCUMFERENCE = 2 * math.pi * _RADIUS


def _point(radius: float, pct: float) -> tuple[float, float]:
    angle = math.radians(-90 + pct * 3.6)  # 0% at 12 o'clock, clockwise
    return 120 + radius * math.cos(angle), 120 + radius * math.sin(angle)


def gauge_svg(pct: Optional[float], settings) -> str:
    value = 0.0 if pct is None else min(max(pct, 0.0), 100.0)
    offset = _CIRCUMFERENCE * (1 - value / 100.0)
    arc_class = "gg-arc gg-arc-empty" if value < 0.3 else "gg-arc"

    ticks = []
    for step in range(0, 100, 5):  # 100% overlaps 0%
        major = step % 25 == 0
        x1, y1 = _point(106 if major else 110, step)
        x2, y2 = _point(116, step)
        ticks.append(
            f'<line class="gg-tick{" gg-tick-major" if major else ""}" '
            f'x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>'
        )
    marks = []
    for threshold, css in ((settings.low_pct, "gg-mark-warn"), (settings.critical_pct, "gg-mark-crit")):
        x1, y1 = _point(103, threshold)
        x2, y2 = _point(119, threshold)
        marks.append(f'<line class="{css}" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>')

    shown = "--" if pct is None else f"{value:.1f}"
    return (
        '<svg class="gg-gauge-svg" viewBox="0 0 240 240" role="img" aria-label="Gas level gauge">'
        f'<circle class="gg-track" cx="120" cy="120" r="{_RADIUS}" fill="none" stroke-width="14"/>'
        f'<circle class="{arc_class} gg-arc-glow" cx="120" cy="120" r="{_RADIUS}" fill="none" stroke-width="24" '
        f'stroke-linecap="round" transform="rotate(-90 120 120)" '
        f'stroke-dasharray="{_CIRCUMFERENCE:.2f}" stroke-dashoffset="{offset:.2f}"/>'
        f'<circle class="{arc_class}" cx="120" cy="120" r="{_RADIUS}" fill="none" stroke-width="14" '
        f'stroke-linecap="round" transform="rotate(-90 120 120)" '
        f'stroke-dasharray="{_CIRCUMFERENCE:.2f}" stroke-dashoffset="{offset:.2f}"/>'
        + "".join(ticks)
        + "".join(marks)
        + f'<text class="gg-gauge-pct" x="120" y="126" text-anchor="middle">{shown}'
        '<tspan class="gg-gauge-sign">%</tspan></text>'
        '<text class="gg-gauge-cap" x="120" y="150" text-anchor="middle">REMAINING</text>'
        "</svg>"
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
        <div class="gg-gauge-wrap">{gauge_svg(gas.level_pct, settings)}</div>
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
