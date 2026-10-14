"""
Shared chart style for TR Power Lab. Every chart on the site is built with these helpers so
colours, fonts, hover and light/dark behaviour stay identical everywhere.

Colours come from assets/palette.json. Each trace stores its light and dark colour in
`meta`; assets/charts.js swaps them when the reader switches the site theme.

    from chart_style import figure, add_area, add_line, add_events
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
PALETTE = json.loads((ROOT / "assets" / "palette.json").read_text(encoding="utf-8"))
SURF = PALETTE["surfaces"]
FONT = '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif'
MODE = "dark"   # the site is dark only; the light values stay in palette.json in case that changes


def colours(family: str, key: str, step: int = 1) -> dict:
    """{'light': hex, 'dark': hex} for a series.

    colours('generation', 'solar'), colours('markets', 'gop'), colours('prices', 'ptf'),
    colours('balancing', 'up', step=0) (code 0 darkest), colours('single', '').
    """
    if family == "single":
        return {"light": PALETTE["single"]["light"], "dark": PALETTE["single"]["dark"]}
    if family == "prices":  # a price wears its market's colour
        return colours("markets", PALETTE["prices"]["market"][key])
    fam = PALETTE[family]
    if family == "balancing":
        pick = lambda m: fam[m][key][step] if isinstance(fam[m][key], list) else fam[m][key]
        return {"light": pick("light"), "dark": pick("dark")}
    if key in fam["light"]:
        return {"light": fam["light"][key], "dark": fam["dark"][key]}
    det = fam["detail"]
    return {"light": det["light"][key], "dark": det["dark"][key]}


def add_bar(fig, x, y, family: str, key: str, name: str | None = None, step: int = 1,
            hover_fmt: str = ",.0f", unit: str = "") -> None:
    """Bars with a hairline surface gap between neighbours."""
    c = colours(family, key, step)
    nm = name or label(family, key)
    fig.add_trace(go.Bar(
        x=x, y=y, name=nm, marker=dict(color=c[MODE], line=dict(width=1, color=SURF[MODE]["surface"])),
        hovertemplate=f"%{{y:{hover_fmt}}}{unit}<extra>{nm}</extra>",
        meta={"light": c["light"], "dark": c["dark"], "kind": "bar"},
    ))


def label(family: str, key: str) -> str:
    labels = PALETTE.get(family, {}).get("labels", {})
    return labels.get(key, key.replace("_", " ").capitalize())


def figure(title: str | None = None, y_title: str | None = None, height: int = 420) -> go.Figure:
    """Empty figure with the site layout: transparent background, hairline grid, unified hover."""
    s = SURF[MODE]
    fig = go.Figure()
    fig.update_layout(
        height=height,
        title=dict(text=title, x=0, xanchor="left", font=dict(size=16)) if title else None,
        font=dict(family=FONT, size=13, color=s["ink"]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=48 if title else 16, b=16),
        hovermode="x unified",
        hoverlabel=dict(font=dict(family=FONT, size=12)),
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, xanchor="left",
                    font=dict(color=s["ink_muted"]), title=None),
        meta={"chart": True},
    )
    axis = dict(showgrid=False, linecolor=s["axis"], tickcolor=s["axis"], ticks="outside",
                tickfont=dict(color=s["ink_muted"]), zeroline=False)
    fig.update_xaxes(**axis)
    fig.update_yaxes(**{**axis, "showgrid": True, "gridcolor": s["grid"], "gridwidth": 1, "ticks": "",
                        "linecolor": "rgba(0,0,0,0)"},
                     title=dict(text=y_title, font=dict(color=s["ink_muted"], size=12)) if y_title else None,
                     separatethousands=True)
    return fig


def add_area(fig, x, y, family: str, key: str, name: str | None = None, hatch: bool = False,
             hover_fmt: str = ",.2f", unit: str = "") -> None:
    """One layer of a stacked area. A thin surface-coloured edge separates neighbouring layers."""
    c = colours(family, key)
    trace = go.Scatter(
        x=x, y=y, name=name or label(family, key), mode="lines", stackgroup="one",
        line=dict(width=1.5, color=SURF[MODE]["surface"]),
        fillcolor=c[MODE],
        hovertemplate=f"%{{y:{hover_fmt}}}{unit}<extra>{name or label(family, key)}</extra>",
        meta={"light": c["light"], "dark": c["dark"], "kind": "area", "hatch": hatch},
    )
    if hatch:
        trace.update(fillpattern=dict(shape="/", fgcolor=c[MODE], bgcolor="rgba(0,0,0,0)", size=6, solidity=0.45),
                     fillcolor="rgba(0,0,0,0)")
    fig.add_trace(trace)


def add_line(fig, x, y, family: str, key: str, name: str | None = None, hover_fmt: str = ",.0f",
             unit: str = "", dash: str | None = None, end_label: bool = True) -> None:
    """A 2px line, optionally with its name written at the right end (direct label)."""
    c = colours(family, key)
    nm = name or label(family, key)
    fig.add_trace(go.Scatter(
        x=x, y=y, name=nm, mode="lines", line=dict(width=2, color=c[MODE], dash=dash),
        hovertemplate=f"%{{y:{hover_fmt}}}{unit}<extra>{nm}</extra>",
        meta={"light": c["light"], "dark": c["dark"], "kind": "line"},
    ))
    if end_label:
        s = pd.Series(list(y), index=list(x)).dropna()
        if len(s):
            fig.add_annotation(x=s.index[-1], y=s.iloc[-1], text=nm.split(" (")[0], showarrow=False,
                               xanchor="left", xshift=6, font=dict(color=SURF[MODE]["ink"], size=12),
                               name="direct-label")


def add_cap_line(fig, x, y, name: str = "Price cap", hover_fmt: str = ",.0f", unit: str = "") -> None:
    """Dashed grey line for a price limit. Steps in lira; in EUR or USD it also moves with the exchange rate."""
    light, dark = SURF["light"]["ink_muted"], SURF["dark"]["ink_muted"]
    fig.add_trace(go.Scatter(
        x=x, y=y, name=name, mode="lines", line=dict(width=1.5, color=(dark if MODE == "dark" else light), dash="dash"),
        hovertemplate=f"%{{y:{hover_fmt}}}{unit}<extra>{name}</extra>",
        meta={"light": light, "dark": dark, "kind": "line"},
    ))


def add_events(fig, events: pd.DataFrame, series: str, include_draft: bool = False,
               min_gap_days: int = 120) -> None:
    """Dotted vertical marker for each event that relates to this series.

    Labels are written only when the previous labelled event is at least `min_gap_days` earlier,
    so clusters do not overlap. Every marker shows its full title and date on hover.
    """
    ev = events[events["series"].fillna("").str.split(";").apply(lambda s: series in s)]
    if not include_draft:
        ev = ev[ev["status"] == "verified"]
    s = SURF[MODE]
    last = None
    for _, e in ev.sort_values("date").iterrows():
        d = pd.Timestamp(e["date"])
        show = last is None or (d - last).days >= min_gap_days
        fig.add_vline(x=d.timestamp() * 1000, line=dict(color=s["axis"], width=1, dash="dot"))
        fig.add_annotation(x=d, y=1, yref="paper", text=e["title"] if show else "▾", showarrow=False,
                           textangle=-90 if show else 0, xanchor="right" if show else "center", yanchor="top",
                           font=dict(size=10, color=s["ink_muted"]), name="event",
                           hovertext=f"{d:%d %b %Y}: {e['title']}")
        if show:
            last = d


def style_controls(fig) -> None:
    """Quiet styling for time-step buttons (updatemenus) and range buttons, matching the site."""
    s = SURF[MODE]
    both = "#7C8B94"  # mid grey: readable on the light and the dark surface
    for um in fig.layout.updatemenus or []:
        um.update(bgcolor="rgba(0,0,0,0)", bordercolor=both, borderwidth=1, font=dict(color=both, size=12))
    fig.update_xaxes(rangeselector=dict(bgcolor="rgba(0,0,0,0)", activecolor=s["grid"],
                                        bordercolor=s["axis"], borderwidth=1,
                                        font=dict(color=s["ink"], size=12)))


def mode_buttons(fig, modes: list[dict], x: float = 0, y: float = 1.03) -> None:
    """Buttons that switch every trace between units (for example EUR/MWh, TL/MWh, % of PTF).

    modes: [{"label": "EUR/MWh", "y": [series per trace], "title": "axis title", "suffix": "",
             "hover": [".1f" per trace]}, ...]. Trace order must match the order they were added in.
    The first mode is drawn by the caller; the y-axis refits whenever a button is pressed.
    """
    def clean(series):
        return [None if pd.isna(v) else round(float(v), 4) for v in series]

    buttons = []
    for md in modes:
        unit = md.get("hover_unit", "")
        hover = [f"%{{y:{h}}}{unit}<extra>{t.name}</extra>" for h, t in zip(md["hover"], fig.data)]
        buttons.append(dict(label=md["label"], method="update",
                            args=[{"y": [clean(v) for v in md["y"]], "hovertemplate": hover},
                                  {"yaxis.title.text": md["title"], "yaxis.ticksuffix": md.get("suffix", ""),
                                   "yaxis.autorange": True}]))
    fig.update_layout(updatemenus=[dict(type="buttons", direction="right", active=0, x=x, y=y,
                                        xanchor="left", yanchor="bottom", buttons=buttons)])


CONFIG = {"displaylogo": False, "responsive": True, "typesetMath": False, "displayModeBar": False,
          "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


def show(fig) -> None:
    """Display a chart in a Quarto page with the site's Plotly settings.

    typesetMath is off so a "$" in a label is never treated as LaTeX (and MathJax is not needed).
    """
    fig.show(config=CONFIG)


def download_link(df: pd.DataFrame, filename: str, label: str) -> str:
    """A button that downloads a table as CSV, built into the page (no separate file needed).

    UTF-8 with a byte-order mark so Excel shows Turkish characters correctly.
    """
    import base64
    data = ("\ufeff" + df.to_csv(index=False)).encode("utf-8")
    href = "data:text/csv;charset=utf-8;base64," + base64.b64encode(data).decode("ascii")
    return (f'<a class="btn btn-sm btn-outline-secondary me-2 mb-2" download="{filename}" href="{href}">'
            f'<i class="bi bi-download"></i> {label}</a>')


def html(fig, div_id: str | None = None) -> str:
    """HTML snippet for a Quarto page. Plotly.js is loaded once by the page, not per chart."""
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id, config=CONFIG)
