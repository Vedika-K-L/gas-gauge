"""GAS GAUGE - Smart LPG monitoring dashboard.   Run:  streamlit run app.py"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make sibling modules importable on any host

st.set_page_config(page_title="Gas Gauge", page_icon="\U0001f525", layout="wide", initial_sidebar_state="collapsed")

import alerts  # noqa: E402
import analytics  # noqa: E402
import config  # noqa: E402
from components import charts  # noqa: E402
from components.common import ago, esc, inject_css, render  # noqa: E402
from components.gas_gauge_3d import render_cylinder_3d  # noqa: E402
from components.demo_panel import render_demo_controls  # noqa: E402
from components.gauge import render_gauge  # noqa: E402
from components.header import render_header  # noqa: E402
from components.live_stats import render_live_stats  # noqa: E402
from components.spotlight import inject_spotlight  # noqa: E402
from components.metric_cards import render_cylinder_details, render_metric_grid  # noqa: E402
from components.notifications import render_alerts, render_mode_banner, toast_new  # noqa: E402
from components.settings_panel import render_settings  # noqa: E402
from runtime import get_runtime  # noqa: E402

_CHART_SUFFIX = {"demo": "", "wokwi": "", "hardware": ""}


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


def main() -> None:
    rt = get_runtime()
    settings = rt.settings
    inject_css(settings.theme)
    inject_spotlight()

    render_header(rt)
    if st.session_state.get("show_settings"):
        render_settings(rt)
    if settings.data_source == "demo":
        render_demo_controls(rt)

    @st.fragment(run_every=settings.refresh_seconds)
    def live_dashboard() -> None:
        s = rt.settings
        mode = s.data_source
        tag = s.source_tag
        theme = s.theme
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
        toast_new(active)

        render_mode_banner(mode)
        render_alerts(active)

        # Centrepiece: 3D cylinder fed by the same readings as every other widget.
        render_cylinder_3d(
            gas_level=gas.level_pct,
            remaining_kg=gas.remaining_kg,
            weight_kg=gas.weight,
            capacity_kg=s.cylinder_capacity_kg,
            data_source=mode,
            connected=conn.code in ("ok", "demo", "imported"),
            low_pct=s.low_pct,
            critical_pct=s.critical_pct,
            medium_pct=s.medium_pct,
        )

        left, right = st.columns([1.25, 1], gap="medium")
        with left:
            render_gauge(gas, s, mode, latest.timestamp if latest else None, snap["source_label"])
        with right:
            render_metric_grid(metrics, conn, ago(latest.timestamp) if latest else "no data yet", s)

        title_col, range_col = st.columns([5, 3], vertical_alignment="center")
        with title_col:
            render('<div class="gg-section-title">Live monitoring</div>')
        with range_col:
            chosen = st.radio("Time range", list(config.TIME_RANGES), key="time_range", horizontal=True,
                              label_visibility="collapsed")

        window_start = now - config.TIME_RANGES[chosen]
        view = df7[df7["ts"] >= window_start]
        downsampled = analytics.downsample(view, config.RANGE_BIN[chosen])
        bucket = config.RANGE_BUCKET[chosen]
        buckets = analytics.consumption_buckets(df7, s, bucket, window_start, now)
        suffix = _CHART_SUFFIX[mode]

        render_live_stats(view, s, chosen, conn.code in ("ok", "demo", "imported"))

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.plotly_chart(charts.level_chart(downsampled, s, theme, suffix), key="chart_level",
                            config={"displayModeBar": False})
        with c2:
            st.plotly_chart(charts.weight_chart(downsampled, s, theme, suffix), key="chart_weight",
                            config={"displayModeBar": False})
        c3, c4 = st.columns([2, 1], gap="medium")
        with c3:
            st.plotly_chart(charts.consumption_chart(buckets, bucket, theme, suffix), key="chart_consumption",
                            config={"displayModeBar": False})
        with c4:
            render_cylinder_details(metrics, s)

        render(
            f'<div class="gg-footer">{esc(config.APP_NAME)} v{config.APP_VERSION} &middot; '
            f'{esc(snap["source_label"])} &middot; {rt.db.count(tag):,} readings stored &middot; '
            f'refresh {s.refresh_seconds:g}s</div>'
        )

    live_dashboard()


main()
