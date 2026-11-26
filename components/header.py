"""Brand block (sidebar) and the slim top bar: page title, mode, connection indicator, clock, mode switch, theme."""
from __future__ import annotations

import base64
from datetime import datetime

import streamlit as st

import alerts
import config
from components.common import esc, render
from runtime import get_runtime

def _logo_html(theme: str) -> str:
    """Logo as an <img> with a data: URI. An <img> survives HTML sanitising that strips inline <svg>."""
    pal = config.THEMES.get(theme, config.THEMES["dark"])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
        f'<rect x="1" y="1" width="46" height="46" rx="13" fill="{pal["forest_deep"]}"/>'
        f'<path d="M24 8c1.2 6.5 9 9.6 9 18.5a9 9 0 0 1-18 0c0-4.3 2.2-6.7 4.4-8.6.2 3.2 1.2 4.6 2.8 5.2C21.3 18.4 22.2 13 24 8z" fill="{pal["lime"]}"/>'
        f'<path d="M15 38.5h18" stroke="{pal["bg"]}" stroke-width="2.4" stroke-linecap="round" opacity=".55"/>'
        "</svg>"
    )
    return f'<img class="gg-logo" alt="Gas Gauge logo" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}">'


def _on_mode_change(rt) -> None:
    rt.update_settings(data_source=st.session_state["mode_quick"])


def _set_theme(rt, theme: str) -> None:
    if rt.settings.theme != theme:
        rt.update_settings(theme=theme)


@st.fragment(run_every=1)
def _status_fragment() -> None:
    """Mode badge, connection pill and clock; refreshes every second on its own."""
    rt = get_runtime()
    settings = rt.settings
    conn = alerts.connection_summary(rt.manager.snapshot(), settings)
    mode = config.MODES[settings.data_source]
    now = config.now()
    render(
        f"""
        <div class="gg-hstatus">
          <span class="gg-badge gg-mode-{esc(settings.data_source)}">{esc(mode['label'])}</span>
          <span class="gg-pill gg-tone-{esc(conn.tone)}" title="{esc(conn.detail)}"><i class="gg-dot"></i>{esc(conn.label)}</span>
          <div class="gg-clock">
            <span class="gg-clock-time">{now:%H:%M:%S}</span>
            <span class="gg-clock-date">{now:%a %d %b %Y}</span>
          </div>
        </div>
        """
    )


def brand_html(theme: str = "dark") -> str:
    return (
        f"""
        <div class="gg-brand">{_logo_html(theme)}
          <div><div class="gg-wordmark">{esc(config.APP_NAME)}</div>
          <div class="gg-subtitle">{esc(config.APP_SUBTITLE)}</div></div>
        </div>
        """
    )


def render_topbar(rt, title: str, subtitle: str) -> None:
    """Slim bar above every view: page title on the left, status / data source / theme on the right."""
    settings = rt.settings
    st.session_state["mode_quick"] = settings.data_source  # keep in sync with the Settings panel

    c_title, c_status, c_mode, c_theme = st.columns([3.0, 4.2, 3.0, 1.6], vertical_alignment="center")
    with c_title:
        render(f'<div class="gg-pagetitle">{esc(title)}</div><div class="gg-pagesub">{esc(subtitle)}</div>')
    with c_status:
        _status_fragment()
    with c_mode:
        st.radio(
            "Data source",
            list(config.MODES),
            key="mode_quick",
            horizontal=True,
            format_func=lambda key: config.MODES[key]["short"],
            label_visibility="collapsed",
            on_change=_on_mode_change,
            args=(rt,),
        )
    with c_theme:  # sun | moon: the lit one is the current theme
        dark = settings.theme == "dark"
        sun, moon = st.columns(2, gap="small")
        with sun:
            st.button("\u200b", key="btn_theme_light", icon=":material/light_mode:", on_click=_set_theme,
                      args=(rt, "light"), type="secondary" if dark else "primary")
        with moon:
            st.button("\u200b", key="btn_theme_dark", icon=":material/dark_mode:", on_click=_set_theme,
                      args=(rt, "dark"), type="primary" if dark else "secondary")
