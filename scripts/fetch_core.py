"""
Download and clean the core hourly series for TR Power Lab.

Series
  prices       PTF (TRY, EUR, USD), SMF, system direction        calls: mcp, mcp-smp-imb
  consumption  real-time consumption                               call:  rt-cons
  generation   real-time generation by source                      call:  rt-gen

What it writes
  data/raw/<series>/<YYYY-MM>.csv     hourly data as EPİAŞ returns it (local only, never committed)
  data/processed/*.csv                small daily, monthly and recent-hourly files the website reads
  data/processed/quality_report.md    gaps, duplicates and checks from the last run

Usage (credentials come from EPTR_USERNAME and EPTR_PASSWORD)
  python scripts/fetch_core.py                          # 2023-01-01 to yesterday
  python scripts/fetch_core.py --start 2024-01-01
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

notes: list[str] = []  # collected for the quality report


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


def download(eptr, start: date, end: date, refresh_months: int) -> None:
    months = list(month_ranges(start, end))
    fresh = {m[0].strftime("%Y-%m") for m in months[-refresh_months:]} if refresh_months else set()

    jobs = {
        "prices": lambda a, b: fetch_prices(eptr, a, b),
        "consumption": lambda a, b: call(eptr, "rt-cons", a, b),
        "generation": lambda a, b: call(eptr, "rt-gen", a, b),
    }
    for series, fetch in jobs.items():
        folder = RAW / series
        folder.mkdir(parents=True, exist_ok=True)
        for first, last in months:
            tag = first.strftime("%Y-%m")
            path = folder / f"{tag}.csv"
            if path.exists() and tag not in fresh:
                continue
            df = fetch(first.isoformat(), last.isoformat())
            if df.empty:
                notes.append(f"No {series} data returned for {tag}.")
                continue
            df.to_csv(path, index=False)
            print(f"  {series:12s} {tag}  {len(df):5d} rows")


def fetch_prices(eptr, start: str, end: str) -> pd.DataFrame:
    """PTF in three currencies from `mcp`, SMF and system direction from `mcp-smp-imb`."""
    mcp = call(eptr, "mcp", start, end)
    need = {"date", "price", "priceEur", "priceUsd"}
    if not need.issubset(mcp.columns):
        raise KeyError(f"mcp columns changed. Expected {sorted(need)}, got {list(mcp.columns)}")
    mcp = mcp[["date", "price", "priceEur", "priceUsd"]].rename(
        columns={"price": "ptf", "priceEur": "ptf_eur", "priceUsd": "ptf_usd"})

    imb = call(eptr, "mcp-smp-imb", start, end)
    need = {"date", "smf", "systemStatus"}
    if not need.issubset(imb.columns):
        raise KeyError(f"mcp-smp-imb columns changed. Expected {sorted(need)}, got {list(imb.columns)}")
    imb = imb[["date", "smf", "systemStatus"]].rename(columns={"systemStatus": "system_direction"})

    # Parse timestamps before merging so small format differences between calls cannot split an hour.
    for d in (mcp, imb):
        d["date"] = pd.to_datetime(d["date"], utc=True).dt.tz_convert(TZ)
    return mcp.merge(imb, on="date", how="outer")


# ---------------------------------------------------------------- cleaning

def load(series: str, start: date, end: date) -> pd.DataFrame:
    files = sorted((RAW / series).glob("*.csv"))
    if not files:
        sys.exit(f"No raw {series} files. Run without --skip-download first.")
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)

    # EPİAŞ timestamps are ISO strings with +03:00; each one marks the start of the hour.
    df["time"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(TZ)
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

    if "total" in df.columns:  # EPİAŞ's own total should match the sum of sources
        gap = (grouped["total"] - df["total"]).abs()
        bad = (gap > 0.01 * df["total"].abs() + 1).sum()
        if bad:
            notes.append(f"generation: {bad} hours where the sum of sources differs from EPİAŞ total by more than 1%.")
    if "importExport" in df.columns:  # cross-border flows, sign as EPİAŞ publishes it
        grouped["import_export"] = df["importExport"]
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
        notes.append(f"prices: {neg} hours with negative PTF. Check against the platform.")
    zero = (df["ptf"] == 0).sum()
    if zero:
        notes.append(f"prices: {zero} hours with PTF = 0 (allowed, kept).")


# ---------------------------------------------------------------- outputs

def build_outputs(prices: pd.DataFrame, cons: pd.DataFrame, gen: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hourly = prices.join(cons[["consumption"]], how="outer").join(gen.add_prefix("gen_"), how="outer")
    hourly["deficit"] = (hourly["system_direction"] == DEFICIT).astype(float)
    hourly["surplus"] = (hourly["system_direction"] == SURPLUS).astype(float)
    hourly.loc[hourly["system_direction"].isna(), ["deficit", "surplus"]] = float("nan")
    hourly["ptf_x_cons"] = hourly["ptf"] * hourly["consumption"]
    gen_cols = [c for c in hourly.columns if c.startswith("gen_")]

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
        "  so solar output and its share are understated.",
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
    prices = load("prices", start, end)
    check_prices(prices)
    check_values("prices", prices, ["ptf", "smf", "ptf_eur"])
    cons = load("consumption", start, end)
    check_values("consumption", cons, ["consumption"])
    gen = clean_generation(load("generation", start, end))
    check_values("generation", gen, ["total"])

    print("Writing outputs …")
    build_outputs(prices, cons, gen)
    write_report(start, end)


if __name__ == "__main__":
    main()
