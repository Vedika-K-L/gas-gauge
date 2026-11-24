"""Bento metric cards and the cylinder details card."""
from __future__ import annotations

from datetime import date
from typing import Optional

import streamlit as st

from components.common import esc, num, render


def metric_card(label: str, value: str, unit: str = "", sub: str = "", tone: str = "none") -> str:
    unit_html = f'<span class="gg-unit">{esc(unit)}</span>' if unit else ""
    return (
        f'<div class="gg-card gg-metric gg-tone-{esc(tone)}">'
        f'<span class="gg-label">{esc(label)}</span>'
        f'<div class="gg-value"><span class="gg-num">{esc(value)}</span>{unit_html}</div>'
        f'<span class="gg-sub">{esc(sub)}</span></div>'
    )


def sensor_card(conn, latest_age: str) -> str:
    detail = conn.detail if len(conn.detail) <= 64 else conn.detail[:61] + "..."
    return (
        '<div class="gg-card gg-metric">'
        '<span class="gg-label">Sensor connection</span>'
        f'<span class="gg-pill gg-tone-{esc(conn.tone)}"><i class="gg-dot"></i>{esc(conn.label)}</span>'
        f'<span class="gg-sub" title="{esc(conn.detail)}">{esc(detail)} &middot; {esc(latest_age)}</span></div>'
    )


def _date(value: Optional[date]) -> str:
    return "—" if value is None else f"{value:%d %b %Y}"


def build_cards(metrics, conn, latest_age: str, settings) -> list[str]:
    gas = metrics.gas
    days = metrics.days_remaining
    if days is None:
        days_value, days_sub = "—", "Needs 6 h+ of data"
    else:
        days_value = f"{days:.1f}"
        days_sub = f"Empty around {_date(metrics.refill_date)}" if metrics.refill_date else "Very low usage"
    return [
        metric_card("Remaining gas", num(gas.remaining_kg), "kg",
                    f"of {settings.cylinder_capacity_kg:.1f} kg capacity", gas.tone),
        metric_card("Consumed today", num(metrics.consumed_today, 2), "kg", "Since 00:00"),
        metric_card("Total cylinder weight", num(gas.weight), "kg",
                    f"Empty {settings.empty_cylinder_weight_kg:.1f} kg"),
        metric_card("Estimated days left", days_value, "days", days_sub,
                    "warn" if days is not None and days < 3 else "none"),
        metric_card("Avg daily consumption", num(metrics.avg_daily, 2), "kg/day", "Last 7 days"),
        sensor_card(conn, latest_age),
    ]


def render_metric_grid(metrics, conn, latest_age: str, settings) -> None:
    cards = build_cards(metrics, conn, latest_age, settings)
    for row in range(0, len(cards), 2):
        columns = st.columns(2, gap="small")
        for column, card in zip(columns, cards[row:row + 2]):
            with column:
                render(card)


def build_cylinder_details(metrics, settings) -> str:
    gas = metrics.gas
    manual = " (manual)" if settings.last_refill_date.strip() else ""
    rows = [
        ("Cylinder capacity", f"{settings.cylinder_capacity_kg:.1f} kg"),
        ("Empty cylinder weight", f"{settings.empty_cylinder_weight_kg:.1f} kg"),
        ("Current total weight", f"{num(gas.weight)} kg"),
        ("Remaining LPG", f"{num(gas.remaining_kg)} kg"),
        ("Last refill", _date(metrics.last_refill) + (manual if metrics.last_refill else "")),
        ("Estimated refill date", _date(metrics.refill_date)),
    ]
    body = "".join(f'<div class="gg-kv"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in rows)
    return f'<div class="gg-card"><div class="gg-card-head"><span class="gg-label">Cylinder details</span></div>{body}</div>'


def render_cylinder_details(metrics, settings) -> None:
    render(build_cylinder_details(metrics, settings))
