"""The dashboard views. Each one is the existing content of the old single page, moved onto its own page.

`build_context` computes the readings once per refresh; every view just draws from it, so all pages
show the same numbers as before (same analytics, same alert rules, same widgets).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import streamlit as st

import alerts
import analytics
import config
from components import charts
from components.common import ago, esc, render
from components.gas_gauge_3d import render_cylinder_3d
from components.gauge import render_gauge
from components.live_stats import render_live_stats
from components.metric_cards import render_cylinder_details, render_metric_grid
from components.notifications import build_alerts_html, render_alerts, render_mode_banner

# Plotly height (px) on the full-screen chart pages: tall enough to read, short enough for one screen.
CHART_HEIGHT = 330


@st.cache_data(ttl=30, show_spinner=False)
def _detect_refill(_db, tag: str, min_raw_delta: float):
    jumps = _db.find_jumps(tag, min_raw_delta, limit=1)
    return date.fromisoformat(jumps[0][0][:10]) if jumps else None


def _last_refill(rt, settings, tag: str):
    manual = settings.last_refill_date.strip()
    if manual:
        return date.fromisoformat(manual)
    factor = settings.calibration_factor if tag == "arduino" else 1.0
    return _detect_refill(rt.db, tag, settings.refill_min_kg / factor)


@dataclass
class Context:
    rt: Any
    s: Any
    mode: str
    tag: str
    theme: str
    now: Any
    snap: dict
    conn: Any
    latest: Any
    gas: Any
    df7: Any
    metrics: Any
    active: list
    connected: bool


def build_context(rt) -> Context:
    s = rt.settings
    tag = s.source_tag
    now = config.now()

    snap = rt.manager.snapshot()
    conn = alerts.connection_summary(snap, s)
    latest = snap["latest"] or rt.db.latest(tag)
    raw_weight = latest.weight if latest is not None else None
    gas = analytics.gas_from_weight(analytics.calibrate_scalar(raw_weight, s, tag), s)

    df7 = analytics.enrich(rt.db.history(tag, since=now - timedelta(days=7)), s, tag)
    metrics = analytics.build_metrics(gas, df7, s, now, _last_refill(rt, s, tag))
    recent = df7[df7["ts"] >= now - timedelta(minutes=alerts.ABNORMAL_WINDOW_MIN * 2)]
    active = alerts.evaluate(snap, conn, gas, recent, s, now)
    return Context(
        rt=rt, s=s, mode=s.data_source, tag=tag, theme=s.theme, now=now, snap=snap, conn=conn, latest=latest,
        gas=gas, df7=df7, metrics=metrics, active=active, connected=conn.code in ("ok", "demo", "imported"),
    )


def _footer(c: Context) -> None:
    render(
        f'<div class="gg-footer">{esc(config.APP_NAME)} v{config.APP_VERSION} &middot; '
        f'{esc(c.snap["source_label"])} &middot; {c.rt.db.count(c.tag):,} readings stored &middot; '
        f'refresh {c.s.refresh_seconds:g}s</div>'
    )


def _gauge(c: Context) -> None:
    render_gauge(c.gas, c.s, c.mode, c.latest.timestamp if c.latest else None, c.snap["source_label"])


# -- views ------------------------------------------------------------------------
def view_overview(c: Context) -> None:
    render_mode_banner(c.mode)
    if c.active:  # one-line summary here; the full printouts are on the Alerts page
        worst = "crit" if any(a.level == "critical" for a in c.active) else "warn"
        n = len(c.active)
        render(
            f'<div class="gg-alertstrip gg-tone-{worst}"><i class="gg-dot"></i>'
            f'{n} ACTIVE ALERT{"S" if n != 1 else ""} &middot; {esc(c.active[0].title)}'
            f'<span class="gg-strip-more">SEE THE ALERTS PAGE</span></div>'
        )
    else:
        render(build_alerts_html(c.active))
    left, right = st.columns([1.25, 1], gap="medium")
    with left:
        _gauge(c)
    with right:
        render_metric_grid(c.metrics, c.conn, ago(c.latest.timestamp) if c.latest else "no data yet", c.s)
    _footer(c)


def view_cylinder(c: Context) -> None:
    render_cylinder_3d(
        gas_level=c.gas.level_pct,
        remaining_kg=c.gas.remaining_kg,
        weight_kg=c.gas.weight,
        capacity_kg=c.s.cylinder_capacity_kg,
        data_source=c.mode,
        connected=c.connected,
        low_pct=c.s.low_pct,
        critical_pct=c.s.critical_pct,
        medium_pct=c.s.medium_pct,
        fill=True,
    )


def _range_row() -> str:
    title_col, range_col = st.columns([5, 3], vertical_alignment="center")
    with title_col:
        render('<div class="gg-section-title">Live monitoring</div>')
    with range_col:
        return st.radio("Time range", list(config.TIME_RANGES), key="time_range", horizontal=True,
                        label_visibility="collapsed")


def view_analytics(c: Context) -> None:
    chosen = _range_row()
    window_start = c.now - config.TIME_RANGES[chosen]
    view = c.df7[c.df7["ts"] >= window_start]
    downsampled = analytics.downsample(view, config.RANGE_BIN[chosen])

    render_live_stats(view, c.s, chosen, c.connected)

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        fig = charts.level_chart(downsampled, c.s, c.theme, "")
        fig.update_layout(height=CHART_HEIGHT)
        st.plotly_chart(fig, key="chart_level", config={"displayModeBar": False})
    with c2:
        fig = charts.weight_chart(downsampled, c.s, c.theme, "")
        fig.update_layout(height=CHART_HEIGHT)
        st.plotly_chart(fig, key="chart_weight", config={"displayModeBar": False})
    _footer(c)


def view_consumption(c: Context) -> None:
    chosen = _range_row()
    window_start = c.now - config.TIME_RANGES[chosen]
    bucket = config.RANGE_BUCKET[chosen]
    buckets = analytics.consumption_buckets(c.df7, c.s, bucket, window_start, c.now)

    c3, c4 = st.columns([2, 1], gap="medium")
    with c3:
        fig = charts.consumption_chart(buckets, bucket, c.theme, "")
        fig.update_layout(height=CHART_HEIGHT + 40)
        st.plotly_chart(fig, key="chart_consumption", config={"displayModeBar": False})
    with c4:
        render_cylinder_details(c.metrics, c.s)
    _footer(c)


def view_alerts(c: Context) -> None:
    render_alerts(c.active)
    s = c.s
    rows = [
        ("Normal above", f"{s.medium_pct:g}%"),
        ("Low gas warning at or below", f"{s.low_pct:g}%"),
        ("Critical gas at or below", f"{s.critical_pct:g}%"),
        ("Abnormal weight change", f"{s.abnormal_delta_kg:g} kg"),
        ("Sensor timeout", f"{s.stale_seconds:g} s"),
        ("Sensor connection", f"{c.conn.label}"),
    ]
    body = "".join(f'<div class="gg-kv"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in rows)
    render(
        '<div class="gg-card"><div class="gg-card-head"><span class="gg-label">Alert thresholds</span>'
        '<span class="gg-sub">change them in Settings &rsaquo; Alerts</span></div>' + body + '</div>'
    )
    _footer(c)


def view_demo_preview(c: Context) -> None:
    """Under the demo controls: the live gauge, so a slider or preset visibly changes the level."""
    _gauge(c)


def view_watch(c: Context) -> None:
    """Pages without live widgets (Settings): nothing to draw, alert toasts still fire."""


LIVE_VIEWS = {
    "overview": view_overview,
    "cylinder": view_cylinder,
    "analytics": view_analytics,
    "consumption": view_consumption,
    "alerts": view_alerts,
    "demo": view_demo_preview,
    "settings": view_watch,
}
