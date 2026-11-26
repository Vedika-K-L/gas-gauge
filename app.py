"""GAS GAUGE - Smart LPG monitoring dashboard.   Run:  streamlit run app.py"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make sibling modules importable on any host

st.set_page_config(page_title="Gas Gauge", page_icon="\U0001f525", layout="wide", initial_sidebar_state="expanded")

from components.common import inject_css  # noqa: E402
from components.demo_panel import render_demo_controls  # noqa: E402
from components.header import render_topbar  # noqa: E402
from components.notifications import toast_new  # noqa: E402
from components.settings_panel import render_settings  # noqa: E402
from components.sidebar import current_view, render_sidebar, view_meta  # noqa: E402
from components.spotlight import inject_spotlight  # noqa: E402
from components.views import LIVE_VIEWS, build_context  # noqa: E402
from runtime import get_runtime  # noqa: E402

# Widgets that live on one page only. Streamlit forgets a widget's value when its page is not drawn, so
# copy these into plain session state: the chosen time range survives a trip to another page.
_REMEMBER = ("time_range",)


def main() -> None:
    rt = get_runtime()
    settings = rt.settings
    for key in _REMEMBER:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]

    inject_css(settings.theme)
    inject_spotlight()

    view = current_view(settings.data_source)
    _, _, _, title, subtitle = view_meta(view)
    render_sidebar(rt, view)
    render_topbar(rt, title, subtitle)

    # Pages with forms / controls are drawn once, outside the auto-refreshing block, so a refresh
    # never resets what the user is typing or dragging.
    if view == "settings":
        render_settings(rt)
    elif view == "demo":
        render_demo_controls(rt)

    @st.fragment(run_every=settings.refresh_seconds)
    def live_dashboard() -> None:
        ctx = build_context(rt)
        toast_new(ctx.active)  # warnings pop up on every page, not just the Alerts page
        LIVE_VIEWS[view](ctx)

    live_dashboard()


main()
