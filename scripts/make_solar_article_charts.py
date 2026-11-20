"""Charts for the article blog/2026-11-solar-market (Why Is the Turkish Solar Market Alarming?).

Reads the two CSVs in blog/2026-11-solar-market/data/ and writes three PNGs to
blog/2026-11-solar-market/images/. Run from anywhere:  python scripts/make_solar_article_charts.py
(The timeline image is made separately; its PNG is already in images/.)
"""
from pathlib import Path
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mtick
import pandas as pd

POST = Path(__file__).resolve().parent.parent / "blog" / "2026-11-solar-market"
DATA, OUT = POST / "data", POST / "images"
OUT.mkdir(exist_ok=True)

INK, MUTE, GRID = "#1f2933", "#5f6b7a", "#e4e7eb"
ACC, BLUE, GREYBAR, GREYLINE = "#b4540a", "#2b6cb0", "#aab4c0", "#8b95a1"
W, H, DPI = 11, 6.4, 200

plt.rcParams.update({
    "font.family": "DejaVu Sans", "axes.edgecolor": GRID, "axes.labelcolor": MUTE,
    "xtick.color": MUTE, "ytick.color": MUTE, "axes.spines.top": False, "axes.spines.right": False,
})


def frame(title, subtitle, source, footnote=None):
    """Figure with title, subtitle and source line; returns fig, ax."""
    fig = plt.figure(figsize=(W, H), dpi=DPI, facecolor="white")
    ax = fig.add_axes([0.075, 0.17, 0.89, 0.63])
    fig.text(0.075, 0.955, "\n".join(textwrap.wrap(title, 92)), fontsize=13.5, fontweight="bold",
             color=INK, va="top", linespacing=1.25)
    fig.text(0.075, 0.885, subtitle, fontsize=10, color=MUTE, va="top")
    y = 0.045
    if footnote:
        fig.text(0.075, 0.075, footnote, fontsize=8.3, color=MUTE, va="center")
        y = 0.04
    fig.text(0.075, y, source, fontsize=8.3, color=MUTE, va="center")
    fig.text(0.965, y, "trpowerlab.com", fontsize=8.3, color=MUTE, va="center", ha="right")
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    return fig, ax


# ---------------------------------------------------------------- chart 1
def chart1():
    d = pd.read_csv(DATA / "solar_support_exit_estimate.csv")
    d = d[d.support_ends_year <= 2035].reset_index(drop=True)
    x = range(len(d))
    gw = d.added_mw / 1000
    cum = d.cumulative_out_of_support_mw / 1000
    fig, ax = frame(
        "About 2.6 GW of solar leaves support in 2027, and 6.7 GW by the end of 2030",
        "Estimated GW leaving YEKDEM per year = solar capacity added 10 years earlier; line = cumulative",
        "Estimate from year-end solar capacity (TEİAŞ / Ministry data via news reports), 2014–2025")
    colors = [ACC if y == 2027 else GREYBAR for y in d.support_ends_year]
    bars = ax.bar(x, gw, width=0.62, color=colors, zorder=3)
    bars[d.index[d.support_ends_year == 2034][0]].set_alpha(0.45)
    for i, v in enumerate(gw):
        yr = d.support_ends_year[i]
        txt = "<0.1" if v < 0.1 else f"{v:.1f}"
        if yr == 2027:   # label inside the highlighted bar, the line passes just above it
            ax.text(i, v / 2, txt, ha="center", va="center", fontsize=10, color="white", fontweight="bold")
        else:
            ax.text(i, max(v, cum[i] if yr < 2027 else 0) + 0.35, txt, ha="center", va="bottom", fontsize=9, color=INK)
    i34 = int(d.index[d.support_ends_year == 2034][0])
    ax.text(i34, gw[i34] + 1.4, "incl. late\nregistration", ha="center", va="bottom", fontsize=8, color=MUTE)
    ax.plot(x, cum, color=INK, lw=1.8, marker="o", ms=4.5, mec="white", mew=1.2, zorder=4)
    i30 = int(d.index[d.support_ends_year == 2030][0])
    ax.annotate("6.7 GW out of support\nby end-2030", (i30, cum[i30]), xytext=(i30 - 1.9, cum[i30] + 7.5),
                fontsize=9.5, color=INK, fontweight="bold", ha="center",
                arrowprops=dict(arrowstyle="-", color=MUTE, lw=0.9))
    ax.text(len(d) - 1, cum.iloc[-1] + 0.9, "24.8 GW by end-2035", ha="right", va="bottom", fontsize=9.5,
            color=INK, fontweight="bold")
    # regime divider between 2030 and 2031
    ax.axvline(i30 + 0.5, color=MUTE, lw=1, ls=(0, (4, 3)))
    ax.text(i30 + 0.4, 29.2, "Commissioned until mid-2021:\nUSD-fixed price", ha="right", va="top", fontsize=8.5, color=MUTE)
    ax.text(i30 + 0.6, 29.2, "From mid-2021: TL YEKDEM\n(2031 mixed)", ha="left", va="top", fontsize=8.5, color=MUTE)
    ax.set_ylim(0, 30)
    ax.set_xlim(-0.6, len(d) - 0.4)
    ax.set_xticks(list(x)); ax.set_xticklabels(d.support_ends_year)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_ylabel("GW")
    ax.set_xlabel("Year support ends (10 years after commissioning)")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=GREYBAR), plt.Line2D([], [], color=INK, marker="o", ms=4.5, lw=1.8)],
              labels=["Capacity leaving support in the year", "Cumulative, out of support"],
              loc="upper left", bbox_to_anchor=(0.0, 0.70), frameon=False, fontsize=9)
    fig.savefig(OUT / "chart1_support_exit.png", dpi=DPI)
    plt.close(fig)


# ---------------------------------------------------------------- chart 2
def chart2():
    d = pd.read_csv(DATA / "solar_monthly_chart_data.csv", parse_dates=["month"])
    a = d.dropna(subset=["capture_rate"]).copy()
    a["year"], a["days"] = a.month.dt.year, a.month.dt.days_in_month
    fig, ax = frame(
        "Solar's capture rate fell from 97% in 2021 to 69% in 2026; in May 2026 it was 17%",
        "Capture price as a share of the average PTF: monthly (grey) and annual, output-weighted (blue). All solar.",
        "Source: EPİAŞ (EXIST) · Jan 2021 – Sep 2026, metered + unlicensed solar")
    ax.plot(a.month, a.capture_rate * 100, color=GREYLINE, lw=1.6, zorder=3)
    ax.axhline(100, color=INK, lw=1, ls=(0, (4, 3)), zorder=2)
    ax.text(pd.Timestamp("2026-10-10"), 102, "= solar earns the\naverage PTF", ha="right", va="bottom", fontsize=8.5, color=INK)
    ticks, labels = [], []
    for y, g in a.groupby("year"):
        w = g.solar_mwh
        rate = (g.capture_tl_mwh * w).sum() / w.sum() / ((g.ptf_tl_mwh * g.days).sum() / g.days.sum()) * 100
        start = pd.Timestamp(f"{y}-01-01")
        end = g.month.max() + pd.offsets.MonthEnd(0)
        ax.hlines(rate, start, end, color=BLUE, lw=3.2, zorder=4)
        ticks.append(start + (end - start) / 2)
        labels.append(f"{y}\n{rate:.0f}%" + ("*" if y == 2026 else ""))
    ax.set_xticks(ticks); ax.set_xticklabels(labels, fontsize=10)
    for t, c in zip(ax.get_xticklabels(), [BLUE] * len(labels)):
        t.set_color(INK)
    may = a[a.month == "2026-05-01"].iloc[0]
    ax.annotate("May 2026: 17%", (may.month, may.capture_rate * 100), xytext=(pd.Timestamp("2025-02-01"), 9),
                fontsize=9.5, fontweight="bold", color=INK, ha="center",
                arrowprops=dict(arrowstyle="-", color=MUTE, lw=0.9))
    ax.set_ylim(0, 115); ax.set_xlim(pd.Timestamp("2020-11-15"), pd.Timestamp("2026-11-15"))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax.set_ylabel("Capture rate")
    ax.tick_params(axis="x", length=0)
    ax.legend(handles=[plt.Line2D([], [], color=GREYLINE, lw=1.6), plt.Line2D([], [], color=BLUE, lw=3.2)],
              labels=["Monthly capture rate", "Annual, output-weighted (*2026 = Jan–Sep)"],
              loc="lower left", bbox_to_anchor=(0.0, 0.0), frameon=False, fontsize=9)
    fig.savefig(OUT / "chart2_capture_rate.png", dpi=DPI)
    plt.close(fig)


# ---------------------------------------------------------------- chart 3
def chart3():
    d = pd.read_csv(DATA / "solar_monthly_chart_data.csv", parse_dates=["month"])
    d = d.dropna(subset=["yekdem_tl_mwh"]).reset_index(drop=True)
    d["capture"] = d.capture_tl_mwh.fillna(d.capture_metered_tl_mwh)
    full = d[d.capture_tl_mwh.notna()]
    tail = d[d.month >= full.month.max()]  # last all-solar month + metered-only months
    fig, ax = frame(
        "The gap between YEKDEM and solar's market value peaked at 2,546 TL/MWh in May 2026",
        "Monthly, nominal TL/MWh. Shaded: YEKDEM above the solar capture price. Until 2024 YEKDEM was mostly below it.",
        "Source: EPİAŞ (EXIST); YEKDEM from EPİAŞ announcements · Jul 2021 – Nov 2026",
        footnote="Dotted capture line Oct–Nov 2026: metered solar only (unlicensed data not yet published); Nov is a partial month.")
    ax.fill_between(d.month, d.capture, d.yekdem_tl_mwh, where=d.yekdem_tl_mwh > d.capture, interpolate=True,
                    color=ACC, alpha=0.16, lw=0, zorder=1)
    ax.plot(d.month, d.ptf_tl_mwh, color=GREYLINE, lw=1.5, ls=(0, (5, 3)), zorder=3)
    ax.plot(full.month, full.capture, color=INK, lw=1.9, zorder=4)
    ax.plot(tail.month, tail.capture, color=INK, lw=1.9, ls=(0, (1, 2)), zorder=4)
    ax.plot(d.month, d.yekdem_tl_mwh, color=ACC, lw=2.8, zorder=5)
    m23 = pd.Timestamp("2023-05-01")
    ax.axvline(m23, color=MUTE, lw=1, ls=(0, (4, 3)), zorder=2)
    ax.text(m23 - pd.Timedelta(days=20), 120, "Decision 7189\nresets the price", ha="right", va="bottom", fontsize=8.5, color=MUTE)
    may = d[d.month == "2026-05-01"].iloc[0]
    ax.annotate("", (may.month, may.capture), (may.month, may.yekdem_tl_mwh),
                arrowprops=dict(arrowstyle="<->", color=INK, lw=1.1, shrinkA=0, shrinkB=0))
    ax.annotate("May 2026 gap:\n2,546 TL/MWh", xy=(may.month, 1350), xytext=(pd.Timestamp("2025-10-20"), 620),
                ha="right", va="center", fontsize=9.5, fontweight="bold", color=INK,
                arrowprops=dict(arrowstyle="-", color=MUTE, lw=0.9))
    ax.set_ylim(0, 4000); ax.set_xlim(pd.Timestamp("2021-06-01"), pd.Timestamp("2026-12-15"))
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylabel("TL/MWh")
    ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(handles=[plt.Line2D([], [], color=ACC, lw=2.8), plt.Line2D([], [], color=INK, lw=1.9),
                       plt.Line2D([], [], color=GREYLINE, lw=1.5, ls=(0, (5, 3)))],
              labels=["YEKDEM solar price", "Solar capture price", "PTF, monthly average"],
              loc="upper left", bbox_to_anchor=(0.0, 1.0), frameon=False, fontsize=9)
    fig.savefig(OUT / "chart3_yekdem_vs_capture.png", dpi=DPI)
    plt.close(fig)


if __name__ == "__main__":
    chart1(); chart2(); chart3()
    print("charts written to", OUT)
