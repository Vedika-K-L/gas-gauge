"""Fixed left navigation sidebar and the view router.

Every dashboard section is one "view". The selected view lives in st.session_state["view"] and is
mirrored into the URL (?view=analytics) so a browser refresh or a shared link opens the same page.
Clicking an item only reruns the script on the open page - the website itself is never reloaded.
"""
from __future__ import annotations

import streamlit as st

import config
from components.common import esc, render
from components.header import brand_html

# (id, label, material icon, page title, one-line description)
VIEWS = (
    ("overview", "Overview", ":material/dashboard:", "Overview", "Live gas level and key readings"),
    ("cylinder", "3D Cylinder", ":material/view_in_ar:", "3D Cylinder", "Interactive model of the cylinder and sensor"),
    ("analytics", "Analytics", ":material/query_stats:", "Analytics", "Level and weight history"),
    ("consumption", "Consumption", ":material/bar_chart:", "Consumption", "Usage per period and cylinder details"),
    ("alerts", "Alerts", ":material/notifications:", "Alerts", "Warnings and thresholds"),
    ("demo", "Demo Controls", ":material/tune:", "Demo Controls", "Test the warning thresholds"),
    ("settings", "Settings", ":material/settings:", "Settings", "Data source, cylinder, alerts and storage"),
)
_BY_ID = {v[0]: v for v in VIEWS}
DEFAULT_VIEW = "overview"


def visible_views(data_source: str) -> list[tuple]:
    """Demo Controls only exists while the data source is the demo generator."""
    return [v for v in VIEWS if v[0] != "demo" or data_source == "demo"]


def view_meta(view: str) -> tuple:
    return _BY_ID.get(view, _BY_ID[DEFAULT_VIEW])


def current_view(data_source: str) -> str:
    """The view to show now: session state first, then ?view= in the URL, else the overview."""
    view = st.session_state.get("view")
    if view is None:
        try:
            view = st.query_params.get("view")
        except Exception:  # very old Streamlit: no query params, state only
            view = None
    allowed = {v[0] for v in visible_views(data_source)}
    if view not in allowed:
        view = DEFAULT_VIEW
    st.session_state["view"] = view
    return view


def _go(view: str) -> None:
    st.session_state["view"] = view
    try:
        st.query_params["view"] = view
    except Exception:
        pass


def render_sidebar(rt, active: str) -> None:
    with st.sidebar:
        render(f'<div class="gg-sidebrand">{brand_html(rt.settings.theme)}</div>')
        with st.container(key="gg_navwrap"):  # the menu sits in the vertical middle of the sidebar
            render('<div class="gg-navlabel">MENU</div>')
            with st.container(key="gg_nav"):
                for view_id, label, icon, *_ in visible_views(rt.settings.data_source):
                    st.button(
                        label,
                        key=f"nav-{view_id}",
                        icon=icon,
                        on_click=_go,
                        args=(view_id,),
                        type="primary" if view_id == active else "secondary",
                    )
        render(f'<div class="gg-sidefoot">{esc(config.APP_NAME)} v{esc(config.APP_VERSION)}</div>')
