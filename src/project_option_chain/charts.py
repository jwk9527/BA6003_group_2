"""Plotly figure builders for the dashboard (one consistent dark theme).

- ``gamma_exposure_figure``: OI by strike, GEX by strike and the aggregate GEX curve
- ``volatility_smile_figure``: call/put IV smiles with the fitted splines
- ``intraday_figure``: the live intraday history
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

from .analytics import fit_iv_smiles
from .models import ChainAnalysis
from .i18n import t
from .fonts import PLOTLY_FONT_FAMILY

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
BG = "#0e1117"          # Streamlit dark background
PANEL = "#161b22"
GRID = "#2a313c"
TEXT = "#d0d6e0"
CALL = "#ef5350"        # red  = calls / positive GEX (A-share convention: red up)
PUT = "#26a69a"         # teal = puts / negative GEX
SPOT = "#64b5f6"
ZERO_G = "#ffb300"
MAX_PAIN = "#ba68c8"
CURVE = "#e0e0e0"
NEUTRAL = "#9e9e9e"
MONTH_COLORS = ["#64b5f6", "#ffb300", "#ba68c8", "#4dd0e1", "#f06292", "#aed581", "#ff8a65", "#9575cd"]
PLOTLY_CONFIG = {"displaylogo": False, "scrollZoom": False}

TEMPLATE_NAME = "option_dark"
pio.templates[TEMPLATE_NAME] = go.layout.Template(
    layout=dict(
        paper_bgcolor=BG,
        plot_bgcolor=PANEL,
        font=dict(family=PLOTLY_FONT_FAMILY, color=TEXT, size=12),
        colorway=[SPOT, CALL, PUT, ZERO_G, MAX_PAIN, CURVE],
        xaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID),
        hoverlabel=dict(bgcolor="#1f2630", bordercolor=GRID, font=dict(family=PLOTLY_FONT_FAMILY, color=TEXT)),
        annotationdefaults=dict(font=dict(family=PLOTLY_FONT_FAMILY)),
        legend=dict(font=dict(family=PLOTLY_FONT_FAMILY), bgcolor="rgba(0,0,0,0)", orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        margin=dict(l=60, r=60, t=70, b=50),
        hovermode="x unified",
    )
)


def show_figure(st, fig: go.Figure, key: str, height: int, hide_weekends: bool = False) -> None:
    """Render a figure with the shared template in Streamlit (``st`` passed in to keep
    this module importable without Streamlit)."""
    fig.update_layout(template=TEMPLATE_NAME, height=height)
    if hide_weekends:  # holiday gaps remain
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CONFIG)


def _finite(value: object) -> float | None:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _vline(fig: go.Figure, x: float, color: str, dash: str, name: str, row: int | None = None,
           y_ref: str = "y domain", width: float = 2, legend: bool = True) -> None:
    """Vertical marker drawn as a scatter trace so it shows in legend + hover."""
    kw = {"row": row, "col": 1} if row else {}
    fig.add_vline(x=x, line=dict(color=color, dash=dash, width=width), **kw)
    if legend:
        fig.add_trace(
            go.Scatter(x=[None], y=[None], mode="lines", name=f"{t(name)}: {x:.3f}",
                       line=dict(color=color, dash=dash, width=width), hoverinfo="skip"),
            **kw,
        )


# ---------------------------------------------------------------------------
# Fig 1: open interest + gamma exposure
# ---------------------------------------------------------------------------
def gamma_exposure_figure(analysis: ChainAnalysis) -> go.Figure:
    options, m, strike_gex = analysis.options, analysis.metrics.iloc[0], analysis.strike_gex
    strikes = np.sort(options["strike_price"].unique())
    call_oi = options.loc[options["is_call"] == 1].groupby("strike_price")["oi"].sum().reindex(strikes, fill_value=0)
    put_oi = options.loc[options["is_put"] == 1].groupby("strike_price")["oi"].sum().reindex(strikes, fill_value=0)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07, row_heights=[0.45, 0.55],
        specs=[[{}], [{"secondary_y": True}]],
        subplot_titles=(t("Open interest by strike"), t("Gamma exposure")),
    )

    # --- top: OI bars
    fig.add_trace(go.Bar(x=strikes, y=call_oi, name=t("Call OI"), marker_color=CALL, offsetgroup="c",
                         text=[f"{v/1000:.0f}k" for v in call_oi], textposition="outside",
                         hovertemplate="Call OI %{y:,.0f}<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Bar(x=strikes, y=put_oi, name=t("Put OI"), marker_color=PUT, offsetgroup="p",
                         text=[f"{v/1000:.0f}k" for v in put_oi], textposition="outside",
                         hovertemplate="Put OI %{y:,.0f}<extra></extra>"), row=1, col=1)
    for key, color, dash, label in (("call_wall", CALL, "solid", "Call wall"),
                                    ("put_wall", PUT, "solid", "Put wall"),
                                    ("max_pain", MAX_PAIN, "dot", "Max pain")):
        v = _finite(m[key])
        if v is not None:
            _vline(fig, v, color, dash, label, row=1)

    # --- bottom: GEX bars (secondary y) + aggregate curve (primary y)
    gex_values = strike_gex["gex_amount"].to_numpy()
    fig.add_trace(go.Bar(x=strike_gex["strike_price"], y=gex_values, name=t("GEX by strike"),
                         marker_color=np.where(gex_values >= 0, CALL, PUT), opacity=0.75,
                         text=[f"{v/1e6:.1f}M" for v in gex_values], textposition="outside",
                         customdata=gex_values / 1e6,
                         hovertemplate="GEX by strike %{customdata:.2f}M<extra></extra>"),
                  row=2, col=1, secondary_y=True)
    curve = analysis.gex_curve
    fig.add_trace(go.Scatter(x=curve["test_price"], y=curve["total_gex"], name=t("Aggregate GEX curve"),
                             mode="lines", line=dict(color=CURVE, width=2),
                             customdata=curve["total_gex"] / 1e6,
                             hovertemplate="Aggregate GEX %{customdata:.2f}M<extra></extra>"),
                  row=2, col=1, secondary_y=False)

    zero_gamma = _finite(m["zero_gamma"])
    x_lo, x_hi = float(strikes.min()), float(strikes.max())
    pad = (x_hi - x_lo) * 0.03 or 0.01
    if zero_gamma is not None:
        fig.add_vrect(x0=x_lo - pad, x1=zero_gamma, fillcolor=CALL, opacity=0.07, line_width=0, row=2, col=1)
        fig.add_vrect(x0=zero_gamma, x1=x_hi + pad, fillcolor=PUT, opacity=0.07, line_width=0, row=2, col=1)
        _vline(fig, zero_gamma, ZERO_G, "solid", "Zero gamma", row=2, width=2.5)
    spot = float(m["spot"])
    fig.add_vline(x=spot, line=dict(color=SPOT, dash="dash", width=2), row=1, col=1)
    _vline(fig, spot, SPOT, "dash", "Spot", row=2)

    # symmetric y-ranges
    c_lim = (float(np.abs(curve["total_gex"]).max()) * 1.15 if len(curve) else 0.0) or 1.0
    b_lim = float(np.abs(gex_values).max()) * 1.25 or 1.0
    fig.update_yaxes(range=[-c_lim, c_lim], title_text=t("Aggregate GEX"), row=2, col=1, secondary_y=False,
                     zeroline=True, zerolinecolor=NEUTRAL)
    fig.update_yaxes(range=[-b_lim, b_lim], title_text=t("GEX by strike"), row=2, col=1, secondary_y=True,
                     showgrid=False)
    fig.update_yaxes(title_text=t("Open interest"), row=1, col=1)
    fig.update_xaxes(range=[x_lo - pad, x_hi + pad], tickvals=strikes,
                     ticktext=[f"{s:.3f}" for s in strikes], tickangle=-45)
    fig.update_xaxes(title_text=t("Strike price"), row=2, col=1)

    # annotation box
    net_gex = float(m["net_gex_million"])
    if zero_gamma is None:
        gamma_message = t("Zero gamma was not found within the simulated range.")
    else:
        dist = (spot - zero_gamma) / zero_gamma * 100
        side = t("above") if dist >= 0 else t("below")
        effect = "E.Stabilizing" if dist >= 0 else "E.Squeezing"
        gamma_message = t("Close prc. {side} zero gamma: {dist}% → <b>{effect}</b>", side=side, dist=f"{dist:+.2f}", effect=t(effect))
    regime = t("Long Gamma") if net_gex >= 0 else t("Short Gamma")
    fig.add_annotation(
        xref="x2 domain", yref="y2 domain", x=0.99, y=0.03, xanchor="right", yanchor="bottom",
        text=t("net GEX: {v} mil.CNY → <b>{regime}</b>", v=f"{net_gex:+.2f}", regime=regime) + f"<br>{gamma_message}",
        showarrow=False, align="right", font=dict(size=13, color=TEXT),
        bgcolor="rgba(22,27,34,0.85)", bordercolor=GRID, borderwidth=1, borderpad=6,
    )
    fig.update_layout(
        template=TEMPLATE_NAME, height=820, barmode="group", bargap=0.25,
        title=dict(text=t("{d} option chain: open interest and gamma exposure", d=m['date']), x=0.01),
        uniformtext=dict(minsize=8, mode="hide"), legend=dict(y=1.05), margin=dict(t=120),
    )
    return fig


# ---------------------------------------------------------------------------
# Fig 2: call / put volatility smiles
# ---------------------------------------------------------------------------
def volatility_smile_figure(analysis: ChainAnalysis) -> go.Figure:
    """Call / put IV vs strike with the CubicSpline fits (fit in K/S, as in 1c)."""
    options = analysis.options
    spot = analysis.metadata.spot
    call_smile, put_smile = fit_iv_smiles(options, spot)
    calls = options.loc[options["is_call"] == 1].sort_values("strike_price")
    puts = options.loc[options["is_put"] == 1].sort_values("strike_price")
    k_all = options["strike_price"].to_numpy(dtype=float)
    span = k_all.max() - k_all.min()
    dense_k = np.linspace(k_all.min() - 0.05 * span, k_all.max() + 0.05 * span, 300)

    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.08, shared_yaxes=True,
                        subplot_titles=(t("Call implied volatility"), t("Put implied volatility")))
    for col, df, spline, dot, line, kind in (
        (1, calls, call_smile, CALL, SPOT, "Call"),
        (2, puts, put_smile, PUT, ZERO_G, "Put"),
    ):
        fig.add_trace(go.Scatter(
            x=df["strike_price"], y=df["iv"], mode="markers", name=t("Market IV ({kind})", kind=kind),
            marker=dict(color=dot, size=9, line=dict(color=BG, width=1)),
            customdata=df["strike_price"] / spot,
            hovertemplate="K %{x:.3f} · K/S %{customdata:.3f}<br>IV %{y:.4f}<extra>" + kind + "</extra>",
        ), row=1, col=col)
        fig.add_trace(go.Scatter(
            x=dense_k, y=np.clip(spline(dense_k / spot), 0.01, 5.0), mode="lines",
            name=t("CubicSpline fit ({kind})", kind=kind), line=dict(color=line, dash="dash", width=1.8),
            hovertemplate="K %{x:.3f}<br>fit IV %{y:.4f}<extra>spline</extra>",
        ), row=1, col=col)
        fig.add_vline(x=spot, line=dict(color=NEUTRAL, dash="dot", width=1.5), row=1, col=col,
                      annotation_text=t("Spot / ATM {s}", s=f"{spot:.3f}"), annotation_position="bottom right",
                      annotation_font_color=NEUTRAL)
        fig.update_xaxes(title_text=t("Strike price"), row=1, col=col)
    iv_max = float(options["iv"].max())
    fig.update_yaxes(title_text=t("Implied volatility"), range=[0, iv_max * 1.3], row=1, col=1)
    fig.update_layout(template=TEMPLATE_NAME, height=460, hovermode="closest", legend=dict(y=1.12))
    return fig


# ---------------------------------------------------------------------------
# Fig 3: intraday history (live mode)
# ---------------------------------------------------------------------------
def intraday_figure(history: pd.DataFrame) -> go.Figure:
    """Spot & zero gamma (left axis) vs net GEX (right axis, bars) over time."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if history is None or history.empty:
        fig.add_annotation(text=t("Waiting for the first snapshot…"), showarrow=False,
                           xref="paper", yref="paper", x=0.5, y=0.5, font=dict(size=14, color=NEUTRAL))
        fig.update_layout(template=TEMPLATE_NAME, height=380)
        return fig
    h = history.sort_values("time")
    gex = h["net_gex_million"].astype(float)
    fig.add_trace(go.Scatter(x=h["time"], y=gex, name=t("Net GEX (M)"), mode="lines", fill="tozeroy",
                             line=dict(color=CALL if gex.iloc[-1] >= 0 else PUT, width=1.5),
                             opacity=0.5, hovertemplate="Net GEX %{y:.2f}M<extra></extra>"), secondary_y=True)
    fig.add_trace(go.Scatter(x=h["time"], y=h["spot"], name=t("Spot"), mode="lines+markers",
                             line=dict(color=SPOT, width=2.5), marker=dict(size=5),
                             hovertemplate="Spot %{y:.4f}<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=h["time"], y=h["zero_gamma"], name=t("Zero gamma"), mode="lines",
                             line=dict(color=ZERO_G, width=2, dash="dash"), connectgaps=False,
                             hovertemplate="Zero gamma %{y:.3f}<extra></extra>"), secondary_y=False)
    for key, color, label in (("call_wall", CALL, t("Call wall")), ("put_wall", PUT, t("Put wall"))):
        if key in h:
            fig.add_trace(go.Scatter(x=h["time"], y=h[key], name=label, mode="lines",
                                     line=dict(color=color, width=1, dash="dot"), line_shape="hv",
                                     hovertemplate=label + " %{y:.3f}<extra></extra>"), secondary_y=False)
    lim = float(np.abs(gex).max()) * 1.2 or 1.0
    fig.update_yaxes(title_text=t("Price"), secondary_y=False)
    fig.update_yaxes(title_text=t("Net GEX (mil. CNY)"), range=[-lim, lim], showgrid=False, secondary_y=True)
    fig.update_xaxes(title_text=t("Time"), tickformat="%H:%M:%S")
    fig.update_layout(template=TEMPLATE_NAME, height=400, bargap=0.1,
                      title=dict(text=t("Intraday: spot vs zero gamma & net GEX"), x=0.01),
                      margin=dict(t=100), legend=dict(y=1.04))
    return fig
