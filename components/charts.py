"""Plotly charts: gas level, weight and consumption."""
from __future__ import annotations

import plotly.graph_objects as go

import config

MONO = "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _style(fig: go.Figure, title: str, t: dict, height: int = 290) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=14, t=46, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=MONO, size=11, color=t["muted"]),
        title=dict(text=title, x=0.02, xanchor="left", font=dict(size=12, color=t["text"], family=MONO)),
        showlegend=False,
        hovermode="x unified",
        uirevision="gg",  # keep zoom/pan across the live refresh
        hoverlabel=dict(bgcolor=t["surface2"], bordercolor=t["border"],
                        font=dict(family=MONO, size=12, color=t["text"])),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=t["border"], zeroline=False, tickfont=dict(size=10))
    fig.update_yaxes(gridcolor=t["grid"], griddash="dot", zeroline=False, tickfont=dict(size=10))
    return fig


def _empty(fig: go.Figure, t: dict) -> go.Figure:
    fig.add_annotation(text="NO DATA IN THIS RANGE YET", xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(family=MONO, size=12, color=t["muted"]))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _threshold(fig: go.Figure, y: float, label: str, color: str) -> None:
    fig.add_hline(y=y, line_dash="dot", line_color=color, line_width=1,
                  annotation_text=label, annotation_position="top left",
                  annotation_font=dict(size=9, color=color, family=MONO))


def _glow_line(fig: go.Figure, x, y, t: dict, hover: str, fill: bool = True) -> None:
    """Soft wide under-stroke + crisp line (neon glow), gradient fill and a marker on the latest point."""
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", connectgaps=False, hoverinfo="skip",
                             line=dict(color=_rgba(t["lime"], 0.16), width=9, shape="spline", smoothing=0.6)))
    main = dict(x=x, y=y, mode="lines", connectgaps=False, hovertemplate=hover,
                line=dict(color=t["lime"], width=2.2, shape="spline", smoothing=0.6))
    if fill:
        try:  # plotly >= 5.24 supports gradient fills
            main.update(fill="tozeroy", fillgradient=dict(
                type="vertical", colorscale=[[0, _rgba(t["forest"], 0.0)], [1, _rgba(t["forest"], 0.38)]]))
        except Exception:
            main.update(fill="tozeroy", fillcolor=_rgba(t["forest"], 0.18))
    try:
        fig.add_trace(go.Scatter(**main))
    except Exception:  # older plotly without fillgradient
        main.pop("fillgradient", None)
        main["fillcolor"] = _rgba(t["forest"], 0.18)
        fig.add_trace(go.Scatter(**main))
    valid = y.dropna() if hasattr(y, "dropna") else y
    if len(valid):
        last = valid.index[-1] if hasattr(valid, "index") else -1
        fig.add_trace(go.Scatter(x=[x[last] if not hasattr(x, "loc") else x.loc[last]], y=[valid.iloc[-1]],
                                 mode="markers", hoverinfo="skip",
                                 marker=dict(color=t["lime"], size=9, line=dict(color=_rgba(t["lime"], 0.35), width=6))))


def level_chart(ds, settings, theme: str, suffix: str = "") -> go.Figure:
    t = config.THEMES[theme]
    fig = go.Figure()
    title = "GAS LEVEL" + suffix
    if ds.empty or ds["level_pct"].notna().sum() == 0:
        return _empty(_style(fig, title, t), t)
    _glow_line(fig, ds["ts"], ds["level_pct"], t, "%{y:.1f}%<extra></extra>")
    _style(fig, title, t)
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    _threshold(fig, settings.low_pct, "LOW", t["amber"])
    _threshold(fig, settings.critical_pct, "CRITICAL", t["red"])
    return fig


def weight_chart(ds, settings, theme: str, suffix: str = "") -> go.Figure:
    t = config.THEMES[theme]
    fig = go.Figure()
    title = "CYLINDER WEIGHT (KG)" + suffix
    if ds.empty or ds["weight"].notna().sum() == 0:
        return _empty(_style(fig, title, t), t)
    _glow_line(fig, ds["ts"], ds["weight"], t, "%{y:.2f} kg<extra></extra>", fill=False)
    _style(fig, title, t)
    _threshold(fig, settings.empty_cylinder_weight_kg, "EMPTY", t["muted"])
    _threshold(fig, settings.full_weight_kg, "FULL", t["muted"])
    return fig


def consumption_chart(buckets, freq: str, theme: str, suffix: str = "") -> go.Figure:
    t = config.THEMES[theme]
    fig = go.Figure()
    title = f"CONSUMPTION {config.BUCKET_LABEL.get(freq, '')}".strip() + suffix
    fig.add_trace(go.Bar(
        x=list(buckets.index), y=[float(v) for v in buckets.values],
        marker=dict(color=_rgba(t["lime"], 0.75), line=dict(color=t["lime"], width=1)),
        hovertemplate="%{y:.3f} kg<extra></extra>",
    ))
    _style(fig, title, t)
    fig.update_layout(bargap=0.25)
    fig.update_yaxes(ticksuffix=" kg")
    return fig
