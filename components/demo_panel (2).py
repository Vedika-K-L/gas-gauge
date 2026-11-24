"""Demo controls: raise/lower the gas level and trigger fault scenarios to test every alert."""
from __future__ import annotations

import streamlit as st

from components.common import render
from demo_generator import SCENARIOS, DemoSource


def _source(rt):
    src = rt.manager.source
    return src if isinstance(src, DemoSource) else None


def _set_scenario(rt) -> None:
    src = _source(rt)
    if src:
        src.command("scenario", st.session_state["demo_scenario"])


def _jump(rt, pct: float) -> None:
    src = _source(rt)
    if src:
        src.command("jump_to_percent", pct)


def _spike(rt, kg: float) -> None:
    src = _source(rt)
    if src:
        src.command("spike", kg)


def render_demo_controls(rt) -> None:
    settings = rt.settings
    with st.expander("DEMO CONTROLS  ·  TEST WARNING THRESHOLDS", expanded=True):
        src = _source(rt)
        if src is None:
            st.caption("Demo generator is starting...")
            return
        state = src.state()
        st.session_state["demo_scenario"] = state["scenario"]
        c1, c2 = st.columns([2, 3], gap="medium")
        with c1:
            st.selectbox("Scenario", list(SCENARIOS), key="demo_scenario",
                         format_func=lambda k: SCENARIOS[k], on_change=_set_scenario, args=(rt,))
        with c2:
            st.slider("Jump to gas level (%)", 0, 100, 50, key="demo_jump_pct")
            st.button("Move gas level to slider value", key="demo_go", on_click=lambda: _jump(rt, st.session_state["demo_jump_pct"]))

        st.markdown("**Quick presets**")
        presets = [
            ("NORMAL", 90.0),
            ("MEDIUM", (settings.low_pct + settings.medium_pct) / 2),
            ("LOW", (settings.critical_pct + settings.low_pct) / 2),
            ("CRITICAL", settings.critical_pct / 2),
        ]
        cols = st.columns(4 + 3, gap="small")
        for col, (label, pct) in zip(cols[:4], presets):
            with col:
                st.button(f"{label} ({pct:.0f}%)", key=f"demo_preset_{label}", on_click=_jump, args=(rt, pct))
        with cols[4]:
            st.button("Spike -3 kg", key="demo_spike_down", on_click=_spike, args=(rt, -3.0))
        with cols[5]:
            st.button("Spike +3 kg", key="demo_spike_up", on_click=_spike, args=(rt, 3.0))
        with cols[6]:
            st.button("Reset demo data", key="demo_reset", on_click=rt.reset_demo)
