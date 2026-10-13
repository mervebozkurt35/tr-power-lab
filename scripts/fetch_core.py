"""
Download and clean the core hourly series for TR Power Lab.

Series (each starts on its own first available date)
  ptf          PTF in TRY, EUR and USD                             call: mcp
  smf          SMF and system direction                            call: mcp-smp-imb
  consumption  real-time consumption                               call: rt-cons
  generation   real-time generation by source                      call: rt-gen

What it writes
  data/raw/<series>/<YYYY-MM>.csv     hourly data as EPİAŞ returns it (local only, never committed)
  data/processed/*.csv                small daily, monthly and recent-hourly files the website reads
  data/processed/quality_report.md    gaps, duplicates and checks from the last run

Usage (credentials come from EPTR_USERNAME and EPTR_PASSWORD)
  python scripts/fetch_core.py                          # 2023-01-01 to yesterday
  python scripts/fetch_core.py --start 2001-01-01      # everything EPİAŞ has; each series starts when its data does
  python scripts/fetch_core.py --refresh-months 3       # re-download the last 3 months

Months already on disk are skipped, except the most recent ones (default 2), because EPİAŞ
revises recent data (PTF objections, generation and consumption corrections).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

TZ = "Europe/Istanbul"  # UTC+3 all year since 2016
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
RECENT_DAYS = 60  # length of the hourly file used for detailed charts

# rt-gen source columns grouped into chart categories.
# Anything not listed here is put in "other" and reported in the quality report.
GEN_GROUPS = {
    "naturalGas": "gas",
    "lng": "gas",
    "lignite": "lignite",
    "importCoal": "imported_coal",
    "blackCoal": "hard_coal",
    "asphaltiteCoal": "hard_coal",
    "dammedHydro": "hydro_dam",
    "river": "hydro_river",
    "wind": "wind",
    "sun": "solar",
    "geothermal": "geothermal",
    "biomass": "biomass",
    "wasteheat": "other",
    "fueloil": "other",
    "naphta": "other",
}
GEN_SKIP = {"date", "hour", "total", "importExport"}  # not generation sources
GEN_ORDER = ["gas", "lignite", "imported_coal", "hard_coal", "hydro_dam", "hydro_river",
             "wind", "solar", "geothermal", "biomass", "other"]

DEFICIT = "Enerji Açığı"   # system short: balancing ordered up
SURPLUS = "Enerji Fazlası"  # system long: balancing ordered down

notes: list[str] = []      # collected for the quality report
coverage: list[str] = []   # first and last hour with data, per column


# ---------------------------------------------------------------- connection

def connect():
    from eptr2 import EPTR2

    user, pwd = os.environ.get("EPTR_USERNAME"), os.environ.get("EPTR_PASSWORD")
    if not user or not pwd:
        sys.exit("Set EPTR_USERNAME and EPTR_PASSWORD first (Colab Secrets or GitHub Secrets).")
    return EPTR2(username=user, password=pwd, use_dotenv=False)


def call(eptr, key: str, start: str, end: str, tries: int = 3) -> pd.DataFrame:
    """One EPİAŞ call with a few retries. Returns an empty frame if there is no data."""
    for attempt in range(1, tries + 1):
        try:
            df = eptr.call(key, start_date=start, end_date=end)
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        except Exception as exc:  # network hiccups, timeouts, expired ticket
            if attempt == tries:
                raise RuntimeError(f"{key} {start}..{end} failed: {exc}") from exc
            time.sleep(3 * attempt)


# ---------------------------------------------------------------- download

def month_ranges(start: date, end: date):
    """Yield (first_day, last_day) for every month touching [start, end]."""
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


def probe(eptr, key: str, day: date) -> bool:
    """True if EPİAŞ returns data for this one day. Errors count as no data."""
    try:
        return not call(eptr, key, day.isoformat(), day.isoformat(), tries=2).empty
    except RuntimeError:
        return False


def first_month_with_data(eptr, key: str, months: list) -> int | None:
    """Index of the first month that has data, by binary search on each month's last day.

    Assumes that once a series starts, it keeps being published. Returns None if even the
    latest month is empty (the series is unavailable or the call is broken).
    """
    if not probe(eptr, key, months[-1][1]):
        return None
    lo, hi = 0, len(months) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if probe(eptr, key, months[mid][1]):
            hi = mid
        else:
            lo = mid + 1
    return lo


def download(eptr, start: date, end: date, refresh_months: int) -> None:
    months = list(month_ranges(start, end))
    fresh = {m[0].strftime("%Y-%m") for m in months[-refresh_months:]} if refresh_months else set()

    for series, (key, fetch) in SERIES.items():
        folder = RAW / series
        folder.mkdir(parents=True, exist_ok=True)
        have = sorted(f.stem for f in folder.glob("*.csv"))
        marker = folder / "_searched_from.txt"  # earliest month already checked for data
        searched = marker.read_text().strip() if marker.exists() else None
        want = months[0][0].strftime("%Y-%m")

        # Find where this series begins, unless an earlier run already searched back this far.
        if have and (have[0] <= want or (searched and searched <= want)):
            first = next((i for i, m in enumerate(months) if m[0].strftime("%Y-%m") >= have[0]), 0)
            first = 0 if have[0] <= want else first
        else:
            upto = [m for m in months if not have or m[0].strftime("%Y-%m") <= have[0]]
            first = first_month_with_data(eptr, key, upto)
            if first is None:
                first = 0 if have else None
        if first is None:
            notes.append(f"{series}: EPİAŞ returned no data at all for `{key}`. Skipped.")
            continue
        marker.write_text(want)
        if first > 0:
            print(f"  {series:12s} starts in {months[first][0]:%Y-%m}; earlier months have no data")

        for a, b in months[first:]:
            tag = a.strftime("%Y-%m")
            path = folder / f"{tag}.csv"
            if path.exists() and tag not in fresh:
                continue
            try:
                df = fetch(eptr, a.isoformat(), b.isoformat())
            except Exception as exc:  # one bad month should not stop the run
                notes.append(f"{series}: {tag} could not be downloaded ({exc}). Run again later.")
                continue
            if df.empty:
                notes.append(f"{series}: no data returned for {tag}.")
                continue
            df.to_csv(path, index=False)
            print(f"  {series:12s} {tag}  {len(df):5d} rows")


def fetch_ptf(eptr, start: str, end: str) -> pd.DataFrame:
    """PTF in TRY, EUR and USD. Older periods may lack the EUR and USD columns; they stay empty."""
    df = call(eptr, "mcp", start, end)
    if df.empty:
        return df
    if not {"date", "price"}.issubset(df.columns):
        raise KeyError(f"mcp columns changed: {list(df.columns)}")
    df = df.reindex(columns=["date", "price", "priceEur", "priceUsd"])
    return df.rename(columns={"price": "ptf", "priceEur": "ptf_eur", "priceUsd": "ptf_usd"})


def fetch_smf(eptr, start: str, end: str) -> pd.DataFrame:
    """SMF and system direction."""
    df = call(eptr, "mcp-smp-imb", start, end)
    if df.empty:
        return df
    if not {"date", "smf"}.issubset(df.columns):
        raise KeyError(f"mcp-smp-imb columns changed: {list(df.columns)}")
    df = df.reindex(columns=["date", "smf", "systemStatus"])
    return df.rename(columns={"systemStatus": "system_direction"})


def fetch_plain(key: str):
    return lambda eptr, start, end: call(eptr, key, start, end)


# Each raw series: (EPİAŞ call used to find its start date, download function).
# Series are stored separately so each one can start on its own first available date.
SERIES = {
    "ptf": ("mcp", fetch_ptf),
    "smf": ("mcp-smp-imb", fetch_smf),
    "consumption": ("rt-cons", fetch_plain("rt-cons")),
    "generation": ("rt-gen", fetch_plain("rt-gen")),
}


# ---------------------------------------------------------------- cleaning

def load(series: str, start: date, end: date) -> pd.DataFrame:
    files = sorted((RAW / series).glob("*.csv"))
    if not files:
        sys.exit(f"No raw {series} files. Run without --skip-download first.")
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)

    # EPİAŞ timestamps are ISO strings with +03:00; each one marks the start of the hour.
    df["time"] = pd.to_datetime(df["date"], utc=True, format="ISO8601").dt.tz_convert(TZ)
    df = df.drop(columns=[c for c in ("date", "hour") if c in df.columns])
    df = df[(df["time"].dt.date >= start) & (df["time"].dt.date <= end)]

    dupes = df["time"].duplicated(keep="last")
    if dupes.any():
        notes.append(f"{series}: dropped {dupes.sum()} duplicate hours (kept the latest download).")
        df = df[~dupes]

    df = df.set_index("time").sort_index()
    expected = pd.date_range(df.index.min().floor("D"), df.index.max().floor("D") + pd.Timedelta(hours=23),
                             freq="h", tz=TZ)
    missing = expected.difference(df.index)
    if len(missing):
        days = sorted({t.date().isoformat() for t in missing})
        shown = ", ".join(days[:10]) + (" …" if len(days) > 10 else "")
        notes.append(f"{series}: {len(missing)} missing hours on {len(days)} days ({shown}). Left as gaps, not filled.")
    return df.reindex(expected).rename_axis("time")


def clean_generation(df: pd.DataFrame) -> pd.DataFrame:
    unknown = [c for c in df.columns if c not in GEN_GROUPS and c not in GEN_SKIP]
    if unknown:
        notes.append(f"generation: new source columns {unknown} were added to 'other'. Review GEN_GROUPS.")
    src = df.drop(columns=[c for c in GEN_SKIP if c in df.columns])
    grouped = src.T.groupby(lambda c: GEN_GROUPS.get(c, "other")).sum(min_count=1).T
    grouped = grouped.reindex(columns=[c for c in GEN_ORDER if c in grouped.columns])
    grouped["total"] = grouped.sum(axis=1, min_count=1)

    # Cross-border flows: positive = net imports, negative = net exports. The sign is confirmed by the
    # night-time balance (consumption = generation + net imports when there is no solar).
    imports = df["importExport"] if "importExport" in df.columns else 0

    if "total" in df.columns:
        # EPİAŞ's total may or may not include net imports, so test both definitions.
        tol = 0.01 * df["total"].abs() + 1
        ok_sources = (grouped["total"] - df["total"]).abs() <= tol
        ok_with_imports = (grouped["total"] + imports - df["total"]).abs() <= tol
        rows = df["total"].notna()
        bad = (rows & ~ok_sources & ~ok_with_imports).sum()
        defn = "sources plus net imports" if ok_with_imports[rows].mean() > ok_sources[rows].mean() else "sources only"
        notes.append(f"generation: EPİAŞ total matches {defn} in "
                     f"{max(ok_sources[rows].mean(), ok_with_imports[rows].mean()):.1%} of hours.")
        if bad:
            notes.append(f"generation: {bad} hours match neither definition (difference above 1%). Check these on the platform.")
    if "importExport" in df.columns:
        grouped["net_imports"] = imports
    return grouped


def check_values(series: str, df: pd.DataFrame, cols: list[str]) -> None:
    """Report hours where the row exists but a key value is empty (e.g. PTF missing, SMF present)."""
    for col in cols:
        if col in df.columns:
            n = df[col].isna().sum()
            if n:
                notes.append(f"{series}: {col} is empty in {n} hours (includes any missing hours above).")


def check_prices(df: pd.DataFrame) -> None:
    neg = (df["ptf"] < 0).sum()
    if neg:
        notes.append(f"ptf: {neg} hours with negative PTF. Check against the platform.")
    zero = (df["ptf"] == 0).sum()
    if zero:
        notes.append(f"ptf: {zero} hours with PTF = 0 (allowed, kept).")


# ---------------------------------------------------------------- outputs

def build_outputs(prices: pd.DataFrame, cons: pd.DataFrame, gen: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hourly = prices.join(cons[["consumption"]], how="outer").join(gen.add_prefix("gen_"), how="outer")
    hourly["deficit"] = (hourly["system_direction"] == DEFICIT).astype(float)
    hourly["surplus"] = (hourly["system_direction"] == SURPLUS).astype(float)
    hourly.loc[hourly["system_direction"].isna(), ["deficit", "surplus"]] = float("nan")
    hourly["ptf_x_cons"] = hourly["ptf"] * hourly["consumption"]
    # Generation missing from the real-time series, mostly unlicensed solar on distribution grids:
    # consumption minus metered generation minus net imports. Close to zero at night, solar shaped by day.
    hourly["embedded_gen_est"] = hourly["consumption"] - hourly["gen_total"] - hourly.get("gen_net_imports", 0)
    gen_cols = [c for c in hourly.columns if c.startswith("gen_")]

    # Each series keeps its own start date. Before it starts, its cells are blank in the output
    # files, and charts begin at the first non-blank value rather than at the earliest date overall.
    for col in ["ptf", "ptf_eur", "smf", "system_direction", "consumption"] + gen_cols:
        if col in hourly.columns and hourly[col].notna().any():
            s = hourly[col]
            coverage.append(f"| {col} | {s.first_valid_index():%Y-%m-%d} | {s.last_valid_index():%Y-%m-%d} |")

    def aggregate(freq: str) -> pd.DataFrame:
        g = hourly.resample(freq)
        out = pd.DataFrame({
            "ptf_mean": g["ptf"].mean(),               # simple average: every hour weighted equally
            "ptf_cons_weighted": g["ptf_x_cons"].sum(min_count=1) / g["consumption"].sum(min_count=1),
            "ptf_min": g["ptf"].min(),
            "ptf_max": g["ptf"].max(),
            "ptf_eur_mean": g["ptf_eur"].mean(),
            "ptf_usd_mean": g["ptf_usd"].mean(),
            "smf_mean": g["smf"].mean(),
            "deficit_share": g["deficit"].mean(),      # share of hours the system was short
            "surplus_share": g["surplus"].mean(),
            "consumption_mwh": g["consumption"].sum(min_count=1),
            "peak_consumption_mw": g["consumption"].max(),
            "hours_with_price": g["ptf"].count(),
        })
        out = out.join(g[gen_cols].sum(min_count=1).rename(columns=lambda c: c.replace("gen_", "") + "_mwh"))
        out["embedded_gen_est_mwh"] = g["embedded_gen_est"].sum(min_count=1)
        out.index = out.index.date if freq == "D" else out.index.strftime("%Y-%m")
        out.index.name = "date" if freq == "D" else "month"
        return out.round(2)

    daily = aggregate("D")
    monthly = aggregate("MS")
    daily.to_csv(OUT / "core_daily.csv")
    monthly.to_csv(OUT / "core_monthly.csv")

    cutoff = hourly.index.max() - pd.Timedelta(days=RECENT_DAYS)
    recent = hourly[hourly.index > cutoff].drop(columns=["ptf_x_cons", "deficit", "surplus"])
    recent.index = recent.index.strftime("%Y-%m-%dT%H:%M%z")
    recent.round(2).to_csv(OUT / "core_hourly_recent.csv")

    for name in ("core_daily.csv", "core_monthly.csv", "core_hourly_recent.csv"):
        size = (OUT / name).stat().st_size / 1024
        print(f"  wrote data/processed/{name}  ({size:,.0f} KB)")


def write_report(start: date, end: date) -> None:
    lines = [
        "# Data quality report",
        "",
        f"Run on {date.today().isoformat()} for {start.isoformat()} to {end.isoformat()}.",
        "",
        "Known limits of the source series:",
        "",
        "- Real-time generation and consumption are operational (SCADA) figures and are revised later.",
        "  Settlement series (UEVM, UEÇM) are final but arrive with a lag of several weeks.",
        "- Real-time generation does not include most small, unlicensed solar connected to distribution grids,",
        "  so solar output and its share are understated. Real-time consumption does include the demand it serves.",
        "  `embedded_gen_est` = consumption - metered generation - net imports estimates the missing generation.",
        "- `net_imports`: positive = net imports, negative = net exports.",
        "",
        "Coverage (first and last day with data):",
        "",
        "| Column | From | To |",
        "|---|---|---|",
        *coverage,
        "",
        "Findings from this run:",
        "",
    ]
    lines += [f"- {n}" for n in notes] if notes else ["- No gaps, duplicates or anomalies found."]
    (OUT / "quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  wrote data/processed/quality_report.md")


# ---------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default=None, help="default: yesterday")
    p.add_argument("--refresh-months", type=int, default=2)
    p.add_argument("--skip-download", action="store_true", help="rebuild outputs from raw files only")
    a = p.parse_args()

    start = date.fromisoformat(a.start)
    end = date.fromisoformat(a.end) if a.end else pd.Timestamp.now(tz=TZ).date() - timedelta(days=1)

    if not a.skip_download:
        print("Downloading from EPİAŞ …")
        download(connect(), start, end, a.refresh_months)

    print("Cleaning …")
    ptf = load("ptf", start, end)
    check_prices(ptf)
    check_values("ptf", ptf, ["ptf", "ptf_eur"])
    smf = load("smf", start, end)
    check_values("smf", smf, ["smf"])
    prices = ptf.join(smf, how="outer")
    cons = load("consumption", start, end)
    check_values("consumption", cons, ["consumption"])
    gen = clean_generation(load("generation", start, end))
    check_values("generation", gen, ["total"])

    print("Writing outputs …")
    build_outputs(prices, cons, gen)
    write_report(start, end)


if __name__ == "__main__":
    main()
