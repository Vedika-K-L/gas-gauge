"""3D LPG cylinder: Python side of the Streamlit custom component.

The component itself is React + Three.js in frontend/ (frontend/src/components/ui/gas-gauge-3d.tsx).
Build it once with `npm install && npm run build` inside frontend/, which produces frontend/dist.

Streamlit cannot import a React component directly. A custom component is the supported route:
Python sends plain values (level, kg, weight, capacity, data source, link state) on every refresh
and the iframe updates the existing scene. The component never talks to the sensor. This module
only forwards what the dashboard already computed.

If frontend/dist is missing the dashboard keeps working and shows a short build hint instead.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from components.common import render

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_declared = None
_declare_failed = False


def is_built() -> bool:
    return (DIST / "index.html").is_file()


def _num(value: Optional[float]) -> Optional[float]:
    """JSON-safe number: None for missing or non-finite values (the viewer draws 'no data')."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _component():
    global _declared, _declare_failed
    if _declared is not None or _declare_failed:
        return _declared
    try:
        import streamlit.components.v1 as components

        _declared = components.declare_component("gas_gauge_3d", path=str(DIST))
    except Exception:  # streamlit missing or too old: fall back to the hint card
        _declare_failed = True
    return _declared


def hint_html() -> str:
    return (
        '<div class="gg-card gg-3d-hint"><div class="gg-card-head"><span class="gg-label">3D cylinder view</span>'
        '<span class="gg-tag">NOT BUILT</span></div>'
        '<p class="gg-sub gg-wrap">Build the 3D viewer once: open a terminal in <b>frontend/</b> and run '
        '<code>npm install</code> then <code>npm run build</code>, then restart Streamlit. '
        'Everything else in the dashboard works without it.</p></div>'
    )


def render_cylinder_3d(
    *,
    gas_level: Optional[float],
    remaining_kg: Optional[float],
    weight_kg: Optional[float],
    capacity_kg: float,
    data_source: str,
    connected: bool,
    low_pct: float,
    critical_pct: float,
    medium_pct: float = 60.0,
    height: int = 520,
    key: str = "gg_cylinder_3d",
) -> bool:
    """Render the 3D viewer. Returns False (after showing a hint) when it is unavailable."""
    component = _component() if is_built() else None
    if component is None:
        render(hint_html())
        return False
    component(
        gasLevel=_num(gas_level),
        remainingGas=_num(remaining_kg),
        cylinderWeight=_num(weight_kg),
        cylinderCapacity=_num(capacity_kg),
        dataSource=data_source,
        connectionStatus="connected" if connected else "disconnected",
        lowThreshold=_num(low_pct),
        criticalThreshold=_num(critical_pct),
        mediumThreshold=_num(medium_pct),
        initialView="cylinder",
        height=height,
        key=key,
        default=None,
    )
    return True
