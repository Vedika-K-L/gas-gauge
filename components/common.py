"""Shared UI helpers: HTML escaping, number formatting, CSS injection."""
from __future__ import annotations

import html
from datetime import datetime
from functools import lru_cache
from typing import Optional

import streamlit as st

import config

_FONTS = (
    "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600"
    "&family=JetBrains+Mono:wght@400;500;600;700&family=VT323&display=swap');"
)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def num(value: Optional[float], digits: int = 2, dash: str = "—") -> str:
    return dash if value is None else f"{value:.{digits}f}"


def ago(iso_ts: Optional[str], now: Optional[datetime] = None) -> str:
    """'12s ago', '4m ago' ... for an ISO timestamp."""
    if not iso_ts:
        return "never"
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return "unknown"
    seconds = int(((now or datetime.now()) - then).total_seconds())
    if seconds < 2:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def render(markup: str) -> None:
    """Render an HTML fragment (no markdown processing, so indentation is harmless)."""
    st.html(markup)


@lru_cache(maxsize=1)
def _stylesheet() -> str:
    return (config.ASSETS_DIR / "styles.css").read_text(encoding="utf-8")


def inject_css(theme: str) -> None:
    palette = config.THEMES.get(theme, config.THEMES["dark"])
    variables = "".join(f"--{key.replace('_', '-')}:{value};" for key, value in palette.items())
    st.markdown(f"<style>{_FONTS}:root{{{variables}}}\n{_stylesheet()}</style>", unsafe_allow_html=True)
