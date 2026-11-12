"""
Exploration for TR Power Lab (nothing here goes on the website yet): look at the results first.

Two questions
  1. Solar capture price: what did solar earn on the day-ahead market on average, compared with the
     average price? Capture price = sum(PTF x solar output) / sum(solar output), hour by hour.
     Capture rate = capture price / average PTF of the same period.
     Solar = metered solar (rt-gen "sun") + unlicensed solar (ren-ul-gen "gunes"). All solar is counted,
     because all of it adds cheap supply in the same hours. Checked on 9 Nov 2026: the unlicensed series
     matches our residual estimate (consumption - metered generation - net imports) within a few percent,
     so the two do not overlap.
     Descriptive only: renewables receive support (for example YEKDEM), so this is a market number,
     not what plants are paid.
  2. GÖP to GİP basis: AOF (intraday weighted average price) minus PTF (day-ahead price), by hour of day
     and month, shown as a heatmap, plus the daily average. AOF is an average of intraday trades in a
     thinner market, so it is not a price one can lock in.

Usage (credentials come from EPTR_USERNAME and EPTR_PASSWORD, as for the other scripts)
  python scripts/explore_capture_basis.py                          # 2021-01-01 to yesterday
  python scripts/explore_capture_basis.py --start 2024-01-01 --end 2026-10-31
  python scripts/explore_capture_basis.py --out my_folder

Writes into the output folder (default: explore_out/)
  capture_daily.csv, capture_monthly.csv, basis_hour_month.csv, basis_daily.csv
  capture_price.html, basis_heatmap.html     (open in a browser)
  summary.md                                 (last 12 months, also shown on the GitHub run page)

Unlicensed generation is published with a lag of about two months. For the newest months only metered
solar exists; those months are in the files with the column solar_total_mwh empty and are NOT drawn
as "all solar" (a separate "metered solar only" line is drawn instead).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_core as fc  # noqa: E402  (connection, retries, month ranges)

TZ = fc.TZ
DEFAULT_START = date(2021, 1, 1)   # unlicensed generation matters for solar from here (see EMBEDDED_FROM)
FAILED: list[str] = []


# ---------------------------------------------------------------- download

def hourly_series(df: pd.DataFrame, col: str, name: str) -> pd.Series:
    """One column of an EPİAŞ frame as an hourly series indexed by Istanbul time."""
    if df.empty or col not in df.columns:
        return pd.Series(dtype=float, name=name)
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").to_numpy(), index=fc._times(df), name=name)
    return s[~s.index.duplicated(keep="last")].sort_index()


def download(eptr, start: date, end: date) -> pd.DataFrame:
    parts: dict[str, list[pd.Series]] = {k: [] for k in ("ptf", "ptf_eur", "aof", "solar_metered", "solar_ul")}
    for a, b in fc.month_ranges(start, end):
        label = a.strftime("%Y-%m")
        jobs = {
            "ptf": (fc.fetch_ptf, [("ptf", "ptf"), ("ptf_eur", "ptf_eur")]),
            "wap": (fc.fetch_wap, [("aof", "aof")]),
            "rt-gen": (fc.fetch_plain("rt-gen"), [("sun", "solar_metered")]),
            "ren-ul-gen": (fc.fetch_plain("ren-ul-gen"), [("gunes", "solar_ul")]),
        }
        for job, (fetch, cols) in jobs.items():
            try:
                df = fc.fetch_month(eptr, fetch, a, b)
            except Exception as exc:  # keep going: one bad month should not stop the run
                FAILED.append(f"{label} {job}: {exc}")
                print(f"  {label} {job}: FAILED ({exc})", flush=True)
                continue
            for col, name in cols:
                s = hourly_series(df, col, name)
                if not s.empty:
                    parts[name].append(s)
        print(f"  {label} done", flush=True)
    h = pd.DataFrame({k: pd.concat(v) if v else pd.Series(dtype=float) for k, v in parts.items()})
    return h[~h.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------- analysis (no network)

def analyse(h: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """h: hourly frame with ptf, ptf_eur, aof, solar_metered, solar_ul (Istanbul time index)."""
    h = h.copy()
    # EUR prices published as 0 while PTF is at least 1 TL are missing values (same rule as fetch_core)
    bad = (h["ptf_eur"] == 0) & (h["ptf"] >= 1)
    h.loc[bad, "ptf_eur"] = np.nan

    h["solar_total"] = h["solar_metered"] + h["solar_ul"]          # empty where unlicensed is not published yet
    for tag, col in (("total", "solar_total"), ("metered", "solar_metered")):
        s = h[col]
        h[f"w_ptf_{tag}"] = h["ptf"] * s
        h[f"w_eur_{tag}"] = h["ptf_eur"] * s
        h[f"s_{tag}"] = s.where(h["ptf"].notna())
        h[f"zero_{tag}"] = s.where(h["ptf"] == 0)

    def aggregate(g) -> pd.DataFrame:
        out = pd.DataFrame(index=g.size().index)
        out["ptf_mean"] = g["ptf"].mean()
        out["ptf_eur_mean"] = g["ptf_eur"].mean()
        for tag in ("total", "metered"):
            solar = g[f"s_{tag}"].sum(min_count=1)
            # a period only counts if every one of its hours has the solar value, otherwise the sum is partial
            complete = g[f"s_{tag}"].count() == g["ptf"].count()
            solar = solar.where(complete & (solar > 0))
            out[f"solar_{tag}_mwh"] = solar
            out[f"capture_{tag}_tl"] = g[f"w_ptf_{tag}"].sum(min_count=1).where(solar.notna()) / solar
            out[f"capture_{tag}_eur"] = g[f"w_eur_{tag}"].sum(min_count=1).where(solar.notna()) / solar
            out[f"capture_rate_{tag}"] = out[f"capture_{tag}_tl"] / out["ptf_mean"]
            out[f"zero_price_share_{tag}"] = g[f"zero_{tag}"].sum(min_count=1).where(solar.notna()) / solar
        return out

    day = h.index.tz_localize(None).normalize()
    month = h.index.tz_localize(None).to_period("M").astype(str)
    daily = aggregate(h.groupby(day))
    daily.index.name = "date"
    monthly = aggregate(h.groupby(month))
    monthly.index.name = "month"

    # GÖP to GİP basis
    h["basis"] = h["aof"] - h["ptf"]
    hour = h.index.hour
    pivot = h.groupby([month, hour])["basis"].mean().unstack()
    pivot.index.name = "month"
    pivot.columns.name = "hour"
    ptf_month = h.groupby(month)["ptf"].mean()
    basis_daily = pd.DataFrame({
        "ptf_mean": h.groupby(day)["ptf"].mean(),
        "aof_mean": h.groupby(day)["aof"].mean(),
        "basis_mean": h.groupby(day)["basis"].mean(),
        "aof_hours": h.groupby(day)["aof"].count(),
    })
    basis_daily.index.name = "date"
    return {"daily": daily, "monthly": monthly, "basis_hour_month": pivot,
            "basis_pct": pivot.div(ptf_month, axis=0), "basis_daily": basis_daily}


# ---------------------------------------------------------------- charts

def charts(res: dict, out: Path) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    m = res["monthly"]
    x = pd.to_datetime(m.index + "-01")
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=("Solar capture price vs average PTF (TL/MWh)",
                                        "Solar capture price vs average PTF (EUR/MWh)",
                                        "Capture rate (capture price / average PTF) and share of solar produced at zero price"))
    fig.add_trace(go.Scatter(x=x, y=m["ptf_mean"], name="Average PTF", line=dict(color="#9aa0a6")), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=m["capture_total_tl"], name="Capture price, all solar", line=dict(color="#f4b400")), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=m["capture_metered_tl"], name="Capture price, metered solar only",
                             line=dict(color="#f4b400", dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=m["ptf_eur_mean"], name="Average PTF (EUR)", line=dict(color="#9aa0a6"),
                             showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=x, y=m["capture_total_eur"], name="Capture price (EUR)", line=dict(color="#f4b400"),
                             showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=x, y=m["capture_rate_total"], name="Capture rate, all solar",
                             line=dict(color="#f4b400")), row=3, col=1)
    fig.add_trace(go.Scatter(x=x, y=m["zero_price_share_total"], name="Share of solar MWh at zero PTF",
                             line=dict(color="#34a853")), row=3, col=1)
    fig.update_yaxes(tickformat=".0%", row=3, col=1)
    fig.update_layout(template="plotly_dark", height=900, hovermode="x unified",
                      title="Solar capture price on the day-ahead market (descriptive: supported plants are not paid this)")
    fig.write_html(out / "capture_price.html", include_plotlyjs="cdn")

    heat = make_subplots(rows=2, cols=1, vertical_spacing=0.12,
                         subplot_titles=("Intraday (AOF) minus day-ahead (PTF), TL/MWh: mean by hour of day and month",
                                         "Same, as a share of the month's average PTF"))
    for row, key, fmt in ((1, "basis_hour_month", ".0f"), (2, "basis_pct", ".0%")):
        p = res[key]
        lim = float(np.nanpercentile(np.abs(p.to_numpy(dtype=float)), 98)) or 1.0
        heat.add_trace(go.Heatmap(z=p.to_numpy(dtype=float), x=[f"{c:02d}:00" for c in p.columns], y=list(p.index),
                                  colorscale="RdBu", zmid=0, zmin=-lim, zmax=lim, showscale=True,
                                  colorbar=dict(len=0.4, y=0.8 if row == 1 else 0.2),
                                  hovertemplate="%{y} %{x}<br>%{z:" + fmt + "}<extra></extra>"), row=row, col=1)
    heat.update_yaxes(autorange="reversed")
    heat.update_layout(template="plotly_dark", height=1500,
                       title="GÖP to GİP basis. Red: intraday above day-ahead; blue: below. Hours without intraday trades are blank.")
    heat.write_html(out / "basis_heatmap.html", include_plotlyjs="cdn")


def summary(res: dict, h: pd.DataFrame, start: date, end: date) -> str:
    m = res["monthly"].tail(12)
    cols = ["ptf_mean", "capture_total_tl", "capture_rate_total", "zero_price_share_total",
            "capture_metered_tl", "capture_rate_metered"]
    t = m[cols].copy()
    for c in ("capture_rate_total", "zero_price_share_total", "capture_rate_metered"):
        t[c] = (t[c] * 100).round(1)
    t = t.round(0).astype({c: "float" for c in cols})
    lines = [f"# Capture price and basis, {start} to {end}", "",
             f"Hours downloaded: {len(h):,}. Hours with all-solar value: {int((h['solar_metered'] + h['solar_ul']).notna().sum()):,}. "
             f"Hours with AOF: {int(h['aof'].notna().sum()):,}.", "",
             "Last 12 months (rates and shares in %; empty = unlicensed solar not published yet):", "",
             t.to_markdown(floatfmt=".0f", missingval="-"), ""]
    if FAILED:
        lines += ["## Downloads that failed", "", *[f"- {f}" for f in FAILED], ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    ap.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--out", default="explore_out")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {args.start} to {args.end} ...", flush=True)
    h = download(fc.connect(), args.start, args.end)
    if h["ptf"].dropna().empty:
        sys.exit("No PTF downloaded. Check the credentials and the dates.")
    h.to_csv(out / "hourly_inputs.csv")

    res = analyse(h)
    res["daily"].round(3).to_csv(out / "capture_daily.csv")
    res["monthly"].round(3).to_csv(out / "capture_monthly.csv")
    res["basis_hour_month"].round(2).to_csv(out / "basis_hour_month.csv")
    res["basis_daily"].round(3).to_csv(out / "basis_daily.csv")
    charts(res, out)
    text = summary(res, h, args.start, args.end)
    (out / "summary.md").write_text(text, encoding="utf-8")
    print(text)
    if FAILED:
        sys.exit(f"{len(FAILED)} downloads failed (see summary.md); the files above were still written.")


if __name__ == "__main__":
    main()
