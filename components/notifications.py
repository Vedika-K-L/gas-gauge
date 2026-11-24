"""Alert banners, toasts and the mode banner."""
from __future__ import annotations

import streamlit as st

from components.common import esc, render

_TONE = {"critical": "crit", "warning": "warn", "info": "mid"}
_TAG = {"critical": "** ALERT **", "warning": "WARN", "info": "NOTICE"}


def build_alerts_html(active, fresh=frozenset()) -> str:
    """Alerts as dot-matrix printouts. Alert codes in `fresh` get the one-off 'printing' animation."""
    if not active:
        return ('<div class="gg-allclear gg-tone-ok"><i class="gg-dot"></i>'
                'ALL SYSTEMS NOMINAL &middot; NO ACTIVE ALERTS</div>')
    items = "".join(
        f'<div class="gg-alert gg-tone-{_TONE[a.level]}{" gg-alert-print" if a.code in fresh else ""}" '
        f'role="{"alert" if a.level == "critical" else "status"}">'
        f'<div class="gg-alert-head"><span>{_TAG[a.level]}</span><span>#{esc(a.code.upper())}</span></div>'
        f'<div class="gg-alert-title">{esc(a.title)}</div><div class="gg-alert-msg">{esc(a.message)}</div></div>'
        for a in active
    )
    return f'<div class="gg-alerts">{items}</div>'


def render_alerts(active) -> None:
    # Only alerts that were not on screen last refresh "print"; unchanged ones stay still.
    codes = {a.code for a in active}
    fresh = codes - st.session_state.get("_printed_alerts", set())
    st.session_state["_printed_alerts"] = codes
    render(build_alerts_html(active, fresh))


def toast_new(active) -> None:
    """Pop a toast the first time a warning/critical alert appears (again after it clears)."""
    current = {a.code for a in active if a.level in ("critical", "warning")}
    seen = st.session_state.get("_seen_alerts", set())
    for alert in active:
        if alert.code in current and alert.code not in seen:
            st.toast(f"**{alert.title.upper()}**  \n{alert.message}", icon="⚠️" if alert.level == "warning" else "\U0001f6a8")
    st.session_state["_seen_alerts"] = current


def render_mode_banner(mode: str) -> None:
    return  # source is already shown by the mode badge in the header
