"""Header: logo, mode, connection indicator, clock, mode switch, theme and settings buttons."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import alerts
import config
from components.common import esc, render
from runtime import get_runtime

_LOGO = """
<svg class="gg-logo" viewBox="0 0 48 48" role="img" aria-label="Gas Gauge logo">
  <rect x="1" y="1" width="46" height="46" rx="13" fill="var(--forest-deep)"/>
  <path d="M24 8c1.2 6.5 9 9.6 9 18.5a9 9 0 0 1-18 0c0-4.3 2.2-6.7 4.4-8.6.2 3.2 1.2 4.6 2.8 5.2C21.3 18.4 22.2 13 24 8z" fill="var(--lime)"/>
  <path d="M15 38.5h18" stroke="var(--bg)" stroke-width="2.4" stroke-linecap="round" opacity=".55"/>
</svg>
"""


def _on_mode_change(rt) -> None:
    rt.update_settings(data_source=st.session_state["mode_quick"])


def _toggle_theme(rt) -> None:
    rt.update_settings(theme="light" if rt.settings.theme == "dark" else "dark")


def _toggle_settings() -> None:
    st.session_state["show_settings"] = not st.session_state.get("show_settings", False)


@st.fragment(run_every=1)
def _status_fragment() -> None:
    """Mode badge, connection pill and clock; refreshes every second on its own."""
    rt = get_runtime()
    settings = rt.settings
    conn = alerts.connection_summary(rt.manager.snapshot(), settings)
    mode = config.MODES[settings.data_source]
    now = datetime.now()
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


def render_header(rt) -> None:
    settings = rt.settings
    st.session_state["mode_quick"] = settings.data_source  # keep in sync with the Settings panel

    c_brand, c_status, c_mode, c_theme, c_settings = st.columns(
        [3.0, 4.0, 3.2, 1.1, 1.3], vertical_alignment="center"
    )
    with c_brand:
        render(
            f"""
            <div class="gg-brand">{_LOGO}
              <div><div class="gg-wordmark">{esc(config.APP_NAME)}</div>
              <div class="gg-subtitle">{esc(config.APP_SUBTITLE)}</div></div>
            </div>
            """
        )
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
    with c_theme:
        dark = settings.theme == "dark"
        st.button(
            "Theme",
            key="btn_theme",
            icon=":material/light_mode:" if dark else ":material/dark_mode:",
            on_click=_toggle_theme,
            args=(rt,),
            help="Switch between the dark and light theme",
        )
    with c_settings:
        st.button(
            "Settings",
            key="btn_settings",
            icon=":material/settings:",
            on_click=_toggle_settings,
            type="primary" if st.session_state.get("show_settings") else "secondary",
        )
