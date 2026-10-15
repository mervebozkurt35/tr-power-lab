"""
Download and clean the extra EPİAŞ series for TR Power Lab (everything beyond fetch_core.py).

Series (each starts on its own first available date)
  gas_spot       spot natural gas market (SGP) prices, daily        call: ng-spot-prices
  gas_balancing  gas balancing prices (BGP), daily                  call: ng-balancing-price
  bpm_up         balancing: upward instructions by code, hourly     call: bpm-up
  bpm_down       balancing: downward instructions by code, hourly   call: bpm-down
  wind           wind farms: generation and forecast, 15 minutes    call: wind-forecast
  load_plan      TEİAŞ load plan (day-ahead demand forecast)        call: load-plan
  gas_direction  gas system direction (daily)                       call: ng-system-direction
  gas_imbalance  gas system imbalance quantity (daily)              call: ng-imbalance-system
  gas_match      SGP matched quantity per gas day                   call: ng-daily-match-qty
  gas_trade      SGP trade value per gas day                        call: ng-daily-trade-volume
  gas_physical   physical gas entry and exit (daily)                call: ng-physical-realization
  ul_gen         YEKDEM unlicensed generation by source, hourly     call: ren-ul-gen (published with a lag)
  congestion     congestion (redispatch) cost by province, monthly  call: congestion-cost
  line_capacity  interconnection line capacities, hourly           call: line-capacities
  line_events    interconnection line outages and maintenance       call: international-line-events
  ren_capacity   YEKDEM installed capacity, licensed and unlicensed, monthly   call: ren-capacity
  reservoirs     reservoir fullness, volume, level: EPİAŞ publishes only the LATEST day,
                 so this script saves one snapshot per run. Run it daily to build the history.

What it writes
  data/raw/<series>/<YYYY-MM>.csv      data as EPİAŞ returns it (local only, never committed)
  data/processed/gas_daily.csv, gas_monthly.csv
  data/processed/balancing_daily.csv, balancing_monthly.csv
  data/processed/wind_daily.csv, load_plan_daily.csv
  data/processed/line_events.csv, ren_capacity_monthly.csv, ul_gen_daily.csv, ul_gen_monthly.csv
  data/processed/congestion_monthly.csv, congestion_province_monthly.csv, line_capacity_daily.csv
  data/processed/reservoirs_national_daily.csv, reservoirs_basin_daily.csv
  data/processed/reservoirs_daily.csv   (long format, one row per dam and day; THE ONLY COPY of this history)
  data/processed/reservoirs_info.csv
  data/processed/quality_report_extra.md

Usage (credentials come from EPTR_USERNAME and EPTR_PASSWORD)
  python scripts/fetch_extra.py                        # everything EPİAŞ has, each series from its first month
  python scripts/fetch_extra.py --only gas             # series whose name contains this text
  python scripts/fetch_extra.py --skip-download        # rebuild the processed files from data/raw
  python scripts/fetch_extra.py --refresh-months 3

Months already on disk are skipped, except the most recent ones (default 2), because EPİAŞ revises
recent data (for example the gas day-after price is filled in a day later).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_core as fc  # noqa: E402  (connection, retries, month ranges)

TZ = fc.TZ
ROOT = fc.ROOT
RAW = fc.RAW
OUT = fc.OUT

# Natural gas energy content. BOTAŞ prices gas on a gross calorific value of 9,155 kcal/Sm3
# (stated in its tariff documents). 1 kcal = 4.1868 kJ, 1 kWh = 3,600 kJ.
# EPİAŞ's spot gas price is assumed to be TL per 1,000 Sm3: to be confirmed against the SGP documentation.
GCV_KCAL_PER_SM3 = 9155
MWH_PER_1000_SM3 = GCV_KCAL_PER_SM3 * 4.1868 / 3600  # about 10.65

notes: list[str] = []

# kind "range": one call per month with start and end dates. "period": one call per month with a first-of-month date.
SERIES = {
    "gas_spot": dict(key="ng-spot-prices", kind="range", time="gasDay", dense=True),
    "gas_balancing": dict(key="ng-balancing-price", kind="range", time="gasDay", dense=True),
    "bpm_up": dict(key="bpm-up", kind="range", time="date", dense=True),
    "bpm_down": dict(key="bpm-down", kind="range", time="date", dense=True),
    "wind": dict(key="wind-forecast", kind="range", time="date", dense=True),
    "load_plan": dict(key="load-plan", kind="range", time="date", dense=True),
    "gas_direction": dict(key="ng-system-direction", kind="range", time="date", dense=True),
    "gas_imbalance": dict(key="ng-imbalance-system", kind="range", time="gasDay", dense=True),
    "gas_match": dict(key="ng-daily-match-qty", kind="range", time="contractName", parse="contract", dense=True),
    "gas_trade": dict(key="ng-daily-trade-volume", kind="range", time="contractName", parse="contract", dense=True),
    "gas_physical": dict(key="ng-physical-realization", kind="range", time="date", dense=True),
    # unlicensed generation is settled with a delay: the newest months are empty
    "ul_gen": dict(key="ren-ul-gen", kind="range", time="date", dense=True, lag=6),
    # congestion cost is one total per province for the whole window, so it is requested month by month
    # with the end date handled exactly (see congestion_end_inclusive)
    "congestion": dict(key="congestion-cost", kind="range", time=None, dense=False, since=date(2015, 1, 1),
                       aggregated=True,
                       variants=[dict(price_type=p, order_type=o) for p in ("SMP", "MCP")
                                 for o in ("UP_REGULATION", "DOWN_REGULATION")]),
    # line capacities have a gap in 2023, so every month is tried instead of searching for the start
    "line_capacity": dict(key="line-capacities", kind="range", time="date", dense=False, since=date(2018, 6, 1),
                          variants=[dict(intl_direction=d) for d in ("TRGR", "GRTR", "TRBG", "BGTR")]),
    "line_events": dict(key="international-line-events", kind="range", time="baslangicTarihi", dense=False),
    "ren_capacity": dict(key="ren-capacity", kind="period", time="period", dense=True),
}
EVENTS_START = date(2015, 1, 1)  # default first month for series without a start search (outages are listed event by event)
END_INCLUSIVE: dict = {}  # filled by congestion_end_inclusive()


# ---------------------------------------------------------------- download

def _local_days(col: pd.Series, parse: str | None = None) -> pd.Series:
    """Calendar day (Istanbul time) of ISO timestamps such as 2026-10-10T00:15:00+03:00, of plain dates,
    or of contract names such as GG20261010 (parse="contract")."""
    s = col.astype(str)
    if parse == "contract":
        return pd.to_datetime(s.str.extract(r"(\d{8})")[0], format="%Y%m%d", errors="coerce").dt.date
    if s.str.len().max() <= 10:
        return pd.to_datetime(s, errors="coerce").dt.date
    return pd.to_datetime(s, utc=True, format="ISO8601", errors="coerce").dt.tz_convert(TZ).dt.date


def call_x(eptr, key: str, start: str, end: str, extra: dict, tries: int = 3) -> pd.DataFrame:
    """Like fetch_core.call, but with extra parameters (direction, price type...)."""
    import time

    for attempt in range(1, tries + 1):
        try:
            df = eptr.call(key, start_date=start, end_date=end, **extra)
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        except Exception as exc:
            if attempt == tries:
                raise RuntimeError(f"{key} {extra} {start}..{end} failed: {exc}") from exc
            time.sleep(3 * attempt)


def congestion_end_inclusive(eptr) -> bool:
    """Does a congestion-cost window include its end date? The call returns one total per province for the
    whole window, so there is no timestamp to filter on. Test it on a month with known costs: if asking for a
    single day returns that day's cost, the end date is included."""
    marker = RAW / "congestion" / "_end_inclusive.txt"
    if marker.exists():
        return marker.read_text().strip() == "yes"
    spec = SERIES["congestion"]
    extra = spec["variants"][0]  # SMP, up regulation
    for a, b in ((date(2023, 3, 1), date(2023, 3, 31)), (date(2026, 9, 1), date(2026, 9, 30))):
        d = a
        while d <= b:
            try:
                same = call_x(eptr, spec["key"], d.isoformat(), d.isoformat(), extra, tries=2)
                nxt = call_x(eptr, spec["key"], d.isoformat(), (d + timedelta(days=1)).isoformat(), extra, tries=2)
            except RuntimeError:
                d += timedelta(days=1)
                continue
            tot = lambda x: pd.to_numeric(x.get("congestionCost"), errors="coerce").sum() if len(x) else 0.0
            if tot(same) > 0 or tot(nxt) > 0:
                result = tot(same) > 0
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("yes" if result else "no")
                print(f"  congestion     end date {'is' if result else 'is not'} included in a window (tested on {d})")
                return result
            d += timedelta(days=1)
    notes.append("congestion: could not test whether the end date is included; assumed yes.")
    return True


def fetch_month(eptr, spec: dict, a: date, b: date) -> pd.DataFrame:
    """One month. Asks for one extra day because some EPİAŞ calls treat the end date as exclusive,
    then keeps only the month's own rows."""
    if spec["kind"] == "period":
        df = _call_period(eptr, spec["key"], a)
        return df.assign(period=a.isoformat()) if not df.empty else df
    if spec.get("aggregated"):  # one total per province for the whole window: the end date must be exact
        if "inclusive" not in END_INCLUSIVE:
            END_INCLUSIVE["inclusive"] = congestion_end_inclusive(eptr)
        end = b if END_INCLUSIVE["inclusive"] else b + timedelta(days=1)
        frames = []
        for extra in spec["variants"]:
            df = call_x(eptr, spec["key"], a.isoformat(), end.isoformat(), extra)
            if not df.empty:
                frames.append(df.assign(**extra))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    variants = spec.get("variants") or [{}]
    frames = []
    for extra in variants:
        df = (call_x(eptr, spec["key"], a.isoformat(), (b + timedelta(days=1)).isoformat(), extra) if extra
              else fc.call(eptr, spec["key"], a.isoformat(), (b + timedelta(days=1)).isoformat()))
        if df.empty:
            continue
        if spec["time"] not in df.columns:
            raise KeyError(f"{spec['key']} columns changed: {list(df.columns)}")
        day = _local_days(df[spec["time"]], spec.get("parse"))
        frames.append(df[(day >= a) & (day <= b)])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _call_period(eptr, key: str, first: date, tries: int = 3) -> pd.DataFrame:
    import time

    for attempt in range(1, tries + 1):
        try:
            df = eptr.call(key, period=first.isoformat())
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        except Exception as exc:
            if attempt == tries:
                raise RuntimeError(f"{key} {first} failed: {exc}") from exc
            time.sleep(3 * attempt)


def has_data(eptr, spec: dict, a: date, b: date) -> bool:
    try:
        return not fetch_month(eptr, spec, a, b).empty
    except RuntimeError:
        return False


def find_first_month(eptr, spec: dict, months: list) -> int | None:
    """Binary search for the first month with data. Assumes that once a series starts it keeps being published.
    Tests the last week of each month, so a series that starts mid-month is found in that month."""
    def ok(i: int) -> bool:
        a, b = months[i]
        return has_data(eptr, spec, max(a, b - timedelta(days=6)), b)

    # the newest month or two may not be published yet, so look for the latest month that has data
    back = 3 + int(spec.get("lag", 0))
    top = next((i for i in range(len(months) - 1, max(len(months) - 1 - back, -1), -1) if ok(i)), None)
    if top is None:
        return None
    lo, hi = 0, top
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def download(eptr, start: date, end: date, refresh_months: int, only: str) -> None:
    for name, spec in SERIES.items():
        if only and only.lower() not in name.lower():
            continue
        s = start if spec["dense"] else spec.get("since", EVENTS_START)
        months = list(fc.month_ranges(max(s, date(2000, 1, 1)), end))
        if spec["kind"] == "period":  # the last full month: the current one is not final
            months = [m for m in months if m[1] < end or m[1] == end]
        folder = RAW / name
        folder.mkdir(parents=True, exist_ok=True)
        have = sorted(f.stem for f in folder.glob("*.csv"))
        n_fresh = max(refresh_months, int(spec.get("lag", 0)))
        fresh = {m[0].strftime("%Y-%m") for m in months[-n_fresh:]} if n_fresh else set()

        marker = folder / "_searched_from.txt"  # earliest month already searched
        want = months[0][0].strftime("%Y-%m")
        searched = marker.read_text().strip() if marker.exists() else None
        if not spec["dense"]:
            first = 0
        elif have and (have[0] <= want or (searched and searched <= want)):
            first = 0 if have[0] <= want else next((i for i, m in enumerate(months)
                                                    if m[0].strftime("%Y-%m") >= have[0]), 0)
        else:
            upto = [m for m in months if not have or m[0].strftime("%Y-%m") <= have[0]]
            first = find_first_month(eptr, spec, upto)
            if first is None:
                first = 0 if have else None
        if first is None:
            notes.append(f"{name}: EPİAŞ returned no data at all for `{spec['key']}` since {s}. Skipped.")
            print(f"  {name:14s} no data found")
            continue
        marker.write_text(want)
        if first > 0 and spec["dense"] and not (have and have[0] <= months[first][0].strftime("%Y-%m")):
            print(f"  {name:14s} starts in {months[first][0]:%Y-%m}; earlier months have no data")

        got = 0
        for a, b in months[first:]:
            tag = a.strftime("%Y-%m")
            path = folder / f"{tag}.csv"
            if path.exists() and tag not in fresh:
                continue
            try:
                df = fetch_month(eptr, spec, a, b)
            except Exception as exc:  # one bad month should not stop the run
                notes.append(f"{name}: {tag} could not be downloaded ({exc}). Run again later.")
                continue
            if df.empty:
                if spec["dense"] and not spec.get("lag"):
                    notes.append(f"{name}: no data returned for {tag}.")
                continue
            df.to_csv(path, index=False)
            got += 1
            print(f"  {name:14s} {tag}  {len(df):6d} rows")
        if not got:
            print(f"  {name:14s} up to date")


# ---------------------------------------------------------------- reservoirs (latest day only)

RESERVOIR_CALLS = {
    "active_fullness_pct": ("dams-active-fullness", "activeFullnessAmount"),
    "active_volume": ("dams-active-volume", "activeVolume"),
    "level_kot": ("dams-daily-level", "dailyKot"),
    "volume": ("dams-daily-volume", "volume"),
    "water_energy": ("dams-water-energy-provision", "energyGeneration"),
}


def snapshot_reservoirs(eptr) -> None:
    """Save today's reservoir figures. The EPİAŞ calls take no date, so the history has to be built one run at a time."""
    frames = []
    for col, (key, val) in RESERVOIR_CALLS.items():
        try:
            df = eptr.call(key)
            df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        except Exception as exc:
            notes.append(f"reservoirs: `{key}` failed ({exc}).")
            continue
        if df.empty or val not in df.columns:
            notes.append(f"reservoirs: `{key}` returned no `{val}` column (columns: {list(df.columns)}).")
            continue
        df = df.rename(columns={"basinName": "basin", "damName": "dam"})
        df["day"] = _local_days(df["date"])
        frames.append(df[["day", "damId", "basin", "dam", val]].rename(columns={val: col, "day": "date"}))
    if not frames:
        return
    snap = frames[0]
    for f in frames[1:]:
        snap = snap.merge(f.drop(columns=["basin", "dam"]), on=["date", "damId"], how="outer")
    snap = snap.rename(columns={"damId": "dam_id"})
    # basin and dam names come from the first call; fill any dam that only the other calls list
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "reservoirs_daily.csv"
    if path.exists():
        old = pd.read_csv(path, parse_dates=["date"]).assign(date=lambda d: d["date"].dt.date)
        snap = pd.concat([old, snap], ignore_index=True)
    snap = snap.drop_duplicates(subset=["date", "dam_id"], keep="last").sort_values(["date", "basin", "dam"])
    snap.to_csv(path, index=False)
    latest = snap["date"].max()
    print(f"  reservoirs     snapshot for {latest}: {int((snap['date'] == latest).sum())} dams, "
          f"{snap['date'].nunique()} days saved")
    try:
        def get(key):
            x = eptr.call(key)
            return x if isinstance(x, pd.DataFrame) else pd.DataFrame(x)

        info = get("dams-info").drop(columns=["date"], errors="ignore")
        for key in ("dams-volume-minmax", "dams-level-minmax"):
            try:
                mm = get(key).drop(columns=["date", "basinName", "damName"], errors="ignore")
                info = info.merge(mm, on="id", how="left")
            except Exception as exc:
                notes.append(f"reservoirs: `{key}` failed ({exc}).")
        info = info.rename(columns={"id": "dam_id", "basinName": "basin", "damName": "dam", "cityName": "city",
                                    "maxVolume": "max_volume", "minVolume": "min_volume",
                                    "maxKot": "max_level_kot", "minKot": "min_level_kot",
                                    "unitFlowRate": "unit_flow_rate", "installedPower": "installed_power"})
        if not info.empty:
            info.to_csv(OUT / "reservoirs_info.csv", index=False)
    except Exception as exc:
        notes.append(f"reservoirs: `dams-info` failed ({exc}).")


# ---------------------------------------------------------------- loading raw files

def load_raw(name: str, time_col: str) -> pd.DataFrame | None:
    files = sorted((RAW / name).glob("*.csv"))
    if not files:
        return None
    df = pd.concat((pd.read_csv(f).assign(_file=f.stem) for f in files), ignore_index=True)
    if time_col in df.columns and name not in ("line_events", "ren_capacity", "congestion", "line_capacity"):
        s = df[time_col].astype(str)
        if SERIES[name].get("parse") == "contract":  # GG20261010 -> that gas day, midnight Istanbul time
            day = pd.to_datetime(s.str.extract(r"(\d{8})")[0], format="%Y%m%d", errors="coerce")
            df["time"] = day.dt.tz_localize(TZ)
        else:
            df["time"] = pd.to_datetime(s, utc=True, format="ISO8601", errors="coerce").dt.tz_convert(TZ)
        bad = int(df["time"].isna().sum())
        if bad:
            notes.append(f"{name}: {bad} rows had an unreadable `{time_col}` and were dropped.")
            df = df[df["time"].notna()]
        before = len(df)
        # the same row can sit in two monthly files (extra day requested); keep the copy from its own month
        df = df.assign(_own=df["time"].dt.strftime("%Y-%m") == df["_file"]).sort_values(["time", "_own"])
        df = df[~df["time"].duplicated(keep="last")]
        if before - len(df):
            notes.append(f"{name}: {before - len(df)} duplicate timestamps removed.")
        df = df.drop(columns=["_own"]).set_index("time").sort_index()
    return df.drop(columns=["_file"], errors="ignore")


def missing_days(days: pd.Series, first, last) -> list:
    full = pd.date_range(first, last, freq="D").date
    return sorted(set(full) - set(days))


def spans(days: list) -> str:
    """Compress a list of dates into 'a..b' ranges for the report."""
    if not days:
        return "none"
    out, start, prev = [], days[0], days[0]
    for d in days[1:] + [None]:
        if d is not None and (d - prev).days == 1:
            prev = d
            continue
        out.append(str(start) if start == prev else f"{start}..{prev}")
        start = prev = d
    return ", ".join(out[:8]) + (f" (+{len(out) - 8} more ranges)" if len(out) > 8 else "")


# ---------------------------------------------------------------- processing

def fx_rates() -> pd.DataFrame | None:
    """Implied daily TL per EUR and per USD, from the PTF in each currency (same method as the price-cap lines)."""
    p = OUT / "core_daily.csv"
    if not p.exists():
        notes.append("gas: data/processed/core_daily.csv not found, so no EUR or USD gas prices.")
        return None
    c = pd.read_csv(p, parse_dates=["date"]).set_index("date")
    r = pd.DataFrame(index=c.index)
    r["eur"] = c["ptf_mean"] / c["ptf_eur_mean"].where(c["ptf_eur_mean"] > 0)
    r["usd"] = c["ptf_mean"] / c["ptf_usd_mean"].where(c["ptf_usd_mean"] > 0)
    return r


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def col(df: pd.DataFrame, name: str) -> pd.Series:
    """A numeric column, or an empty (NaN) one if EPİAŞ stops publishing it."""
    if name not in df.columns:
        notes.append(f"column `{name}` is missing from the raw data; left empty.")
        return pd.Series(float("nan"), index=df.index)
    return num(df[name])


def build_gas(report: list) -> None:
    spot, bal = load_raw("gas_spot", "gasDay"), load_raw("gas_balancing", "gasDay")
    if spot is None and bal is None:
        return
    parts = []
    if spot is not None:
        s = pd.DataFrame({
            "sgp_day_ahead": col(spot, "dayAheadPrice"), "sgp_intraday": col(spot, "intraDayPrice"),
            "sgp_day_after": col(spot, "dayAfterPrice"), "sgp_wavg": col(spot, "weightedAverage")})
        s.index = s.index.date
        parts.append(s)
    if bal is not None:
        b = pd.DataFrame({
            "bgp_add_purchase": col(bal, "additionalBalancingPurchase"), "bgp_add_sale": col(bal, "additionalBalancingSale"),
            "bgp_buy": col(bal, "balancingGasPurchase"), "bgp_sell": col(bal, "balancingGasSale")})
        b.index = b.index.date
        parts.append(b)
    d = pd.concat(parts, axis=1).sort_index()
    d.index = pd.to_datetime(d.index)
    d.index.name = "date"

    # extra daily gas series: system direction and imbalance, spot matched quantity and value, physical flows
    extras = {}

    def put(name, raw, colname, text=False):
        if raw is None:
            return
        x = (raw[colname] if colname in raw else pd.Series(float("nan"), index=raw.index)) if text else col(raw, colname)
        x = x.copy()
        x.index = x.index.tz_convert(TZ).tz_localize(None).normalize()
        extras[name] = x[~x.index.duplicated(keep="last")]

    put("gas_system_direction", load_raw("gas_direction", "date"), "systemDirection", text=True)
    put("gas_system_imbalance", load_raw("gas_imbalance", "gasDay"), "imbalance")
    put("sgp_matched_qty", load_raw("gas_match", "contractName"), "total")
    put("sgp_trade_value_tl", load_raw("gas_trade", "contractName"), "tradeValueTotal")
    phys = load_raw("gas_physical", "date")
    put("gas_physical_entry", phys, "physicalEntry")
    put("gas_physical_exit", phys, "physicalExit")
    if extras:
        d = d.join(pd.DataFrame(extras), how="outer")
        d.index.name = "date"
    if "sgp_wavg" in d and "bgp_buy" in d:
        d["bgp_buy_premium_pct"] = (d["bgp_buy"] / d["sgp_wavg"] - 1) * 100
        d["bgp_sell_discount_pct"] = (1 - d["bgp_sell"] / d["sgp_wavg"]) * 100
    if "sgp_wavg" in d:
        d["sgp_wavg_tl_mwh"] = d["sgp_wavg"] / MWH_PER_1000_SM3
    fx = fx_rates()
    if fx is not None:
        fx = fx.reindex(d.index)
        for c in ("sgp_wavg", "bgp_buy", "bgp_sell"):
            if c in d:
                d[f"{c}_eur"] = d[c] / fx["eur"]
                d[f"{c}_usd"] = d[c] / fx["usd"]
        if "sgp_wavg_tl_mwh" in d:
            d["sgp_wavg_eur_mwh"] = d["sgp_wavg_tl_mwh"] / fx["eur"]
            d["sgp_wavg_usd_mwh"] = d["sgp_wavg_tl_mwh"] / fx["usd"]
        miss = int(fx["eur"].isna().sum())
        if miss:
            notes.append(f"gas: {miss} gas days have no implied exchange rate (PTF in EUR missing or zero); "
                         "EUR and USD prices are empty on those days.")
    d.round(4).to_csv(OUT / "gas_daily.csv")
    m = d.select_dtypes("number").drop(columns=[c for c in d.columns if c.endswith("_pct")]).resample("MS").mean()
    for c in ("bgp_buy_premium_pct", "bgp_sell_discount_pct"):
        if c in d:
            m[c] = d[c].resample("MS").mean()
    m.index = m.index.strftime("%Y-%m")
    m.index.name = "month"
    m.round(4).to_csv(OUT / "gas_monthly.csv")

    first, last = d.index.min().date(), d.index.max().date()
    gaps = missing_days(d.index.date, first, last)
    report.append(f"## Gas prices (SGP and BGP)\n\n- Range: {first} to {last}, {len(d)} days.\n"
                  f"- Days without a row: {len(gaps)} ({spans(gaps)}).\n"
                  f"- Unit assumed: TL per 1,000 Sm3 as published; TL/MWh uses {GCV_KCAL_PER_SM3} kcal/Sm3 "
                  f"(1,000 Sm3 = {MWH_PER_1000_SM3:.2f} MWh). Both to be confirmed.")
    for c in ("sgp_wavg", "bgp_buy", "bgp_sell"):
        if c in d:
            v = d[c].dropna()
            report.append(f"- `{c}`: {len(v)} values, min {v.min():,.0f}, median {v.median():,.0f}, max {v.max():,.0f}; "
                          f"zero or negative: {int((v <= 0).sum())}.")
    if "sgp_wavg" in d:
        jump = d["sgp_wavg"].pct_change().abs()
        big = d.index[jump > 0.5]
        report.append(f"- Day-on-day moves above 50% in the spot price: {len(big)}"
                      + (f" (first: {', '.join(str(x.date()) for x in big[:5])})." if len(big) else "."))
    if "bgp_buy" in d and "bgp_sell" in d:
        inv = int((d["bgp_buy"] < d["bgp_sell"]).sum())
        report.append(f"- Days where the balancing purchase price is below the sale price (unexpected): {inv}.")
    if {"sgp_matched_qty", "sgp_trade_value_tl", "sgp_wavg"}.issubset(d.columns):
        implied = d["sgp_trade_value_tl"] / d["sgp_matched_qty"].where(d["sgp_matched_qty"] > 0)
        gap = (implied / d["sgp_wavg"] - 1).abs().dropna()
        if len(gap):
            report.append(f"- Spot trade value divided by matched quantity versus the weighted average price: median gap "
                          f"{gap.median():.2%}, above 1% on {int((gap > .01).sum())} of {len(gap)} days. Agreement means the price "
                          "is per quantity unit; the unit itself (assumed 1,000 Sm3) is still unconfirmed.")
    if {"sgp_matched_qty", "gas_physical_entry"}.issubset(d.columns):
        share = (d["sgp_matched_qty"] * 1000 / d["gas_physical_entry"]).dropna()
        if len(share):
            report.append(f"- Spot matched quantity as a share of physical gas entry (if the quantity is in 1,000 Sm3, "
                          f"entry in Sm3): median {share.median():.2%}, max {share.max():.2%}.")
    if {"gas_system_direction", "gas_system_imbalance"}.issubset(d.columns):
        sign = pd.Series(["positive" if v > 0 else "negative" if v < 0 else "zero" for v in d["gas_system_imbalance"].fillna(0)],
                         index=d.index)
        ct = pd.crosstab(d["gas_system_direction"].fillna("missing"), sign)
        report.append("- System direction (as published) against the sign of the system imbalance, number of days:\n\n"
                      + ct.to_markdown() + "\n\n  Do not label either direction 'short' or 'long' on the site until the match is understood.")
    report.append("")


def build_balancing(report: list) -> None:
    up, dn = load_raw("bpm_up", "date"), load_raw("bpm_down", "date")
    if up is None and dn is None:
        return
    cols = {}
    if up is not None:
        for src, dst in [("upRegulationZeroCoded", "up_code0_mwh"), ("upRegulationOneCoded", "up_code1_mwh"),
                         ("upRegulationTwoCoded", "up_code2_mwh"), ("upRegulationDelivered", "up_delivered_mwh")]:
            cols[dst] = col(up, src)
    if dn is not None:
        for src, dst in [("downRegulationZeroCoded", "down_code0_mwh"), ("downRegulationOneCoded", "down_code1_mwh"),
                         ("downRegulationTwoCoded", "down_code2_mwh"), ("downRegulationDelivered", "down_delivered_mwh")]:
            cols[dst] = col(dn, src)
    h = pd.DataFrame(cols)
    if up is not None and "net" in up:
        h["net_mwh"] = col(up, "net")
    h = h.sort_index()
    day = h.index.tz_localize(None).normalize() if h.index.tz is None else h.index.tz_convert(TZ).tz_localize(None).normalize()
    daily = h.groupby(day).sum(min_count=1)
    daily["hours"] = h.groupby(day).size()
    daily.index.name = "date"
    daily.round(3).to_csv(OUT / "balancing_daily.csv")
    mon = h.groupby(day.to_period("M").astype(str)).sum(min_count=1)
    mon["hours"] = h.groupby(day.to_period("M").astype(str)).size()
    mon.index.name = "month"
    mon.round(3).to_csv(OUT / "balancing_monthly.csv")

    first, last = daily.index.min().date(), daily.index.max().date()
    short = daily[daily["hours"] < 24]
    report.append(f"## Balancing instructions (bpm-up, bpm-down)\n\n- Range: {first} to {last}, {len(daily)} days, "
                  f"{int(daily['hours'].sum()):,} hours.\n"
                  f"- Days with fewer than 24 hours: {len(short)} ({spans([x.date() for x in short.index])}).")
    if {"up_delivered_mwh", "down_delivered_mwh"}.issubset(h.columns):
        a = h["up_delivered_mwh"].fillna(0) + h["down_delivered_mwh"].fillna(0)
        if "net_mwh" in h:
            diff = (a - h["net_mwh"]).abs()
            report.append(f"- Check: up delivered + down delivered vs `net` differ by more than 1 MWh in "
                          f"{int((diff > 1).sum())} of {int(diff.notna().sum())} hours.")
        report.append(f"- Down-delivered values are negative in {int((h['down_delivered_mwh'] < 0).sum())} hours "
                      f"and positive in {int((h['down_delivered_mwh'] > 0).sum())} (sign convention check).")
    report.append("- Instruction code 0, 1 and 2 are published as is; their exact meaning is not documented here yet "
                  "(code 1 is expected to be grid-constraint instructions). Do not describe them on the site until confirmed.\n")


def build_wind(report: list) -> None:
    w = load_raw("wind", "date")
    if w is None:
        return
    q = pd.DataFrame({"generation": col(w, "generation"), "forecast": col(w, "forecast")}).sort_index()
    q["error"] = q["forecast"] - q["generation"]
    day = q.index.tz_convert(TZ).tz_localize(None).normalize()
    g = q.groupby(day)
    daily = pd.DataFrame({
        "wind_gen_mw": g["generation"].mean(), "wind_forecast_mw": g["forecast"].mean(),
        "wind_gen_mwh": g["generation"].sum() * 0.25, "wind_forecast_mwh": g["forecast"].sum() * 0.25,
        "wind_mae_mw": g["error"].apply(lambda s: s.abs().mean()), "wind_bias_mw": g["error"].mean(),
        "quarters": g.size()})
    daily["wind_mae_pct_of_gen"] = daily["wind_mae_mw"] / daily["wind_gen_mw"] * 100
    daily.index.name = "date"
    core = OUT / "core_daily.csv"
    cover = None
    if core.exists():
        c = pd.read_csv(core, parse_dates=["date"]).set_index("date")
        if "wind_mwh" in c:
            daily["rt_gen_wind_mwh"] = c["wind_mwh"].reindex(daily.index)
            daily["monitored_share_of_rt_wind"] = daily["wind_gen_mwh"] / daily["rt_gen_wind_mwh"]
            cover = daily["monitored_share_of_rt_wind"].dropna()
    daily.round(3).to_csv(OUT / "wind_daily.csv")

    first, last = daily.index.min().date(), daily.index.max().date()
    short = daily[daily["quarters"] < 96]
    report.append(f"## Wind generation and forecast (wind-forecast)\n\n- Range: {first} to {last}, {len(daily)} days, "
                  f"{len(q):,} quarter-hours.\n"
                  f"- Days with fewer than 96 quarter-hours: {len(short)} ({spans([x.date() for x in short.index])}).\n"
                  f"- Missing forecast values: {int(q['forecast'].isna().sum())}; missing generation values: "
                  f"{int(q['generation'].isna().sum())}.")
    extra = [c for c in ("quarter1", "quarter2", "quarter3", "quarter4") if c in w]
    if extra:
        nz = {c: int((num(w[c]) != 0).sum()) for c in extra}
        report.append(f"- Columns `quarter1`..`quarter4` (prediction bands, meaning unconfirmed): non-zero rows {nz}.")
    if cover is not None and len(cover):
        report.append(f"- Share of real-time wind generation (rt-gen) covered by the monitored farms: "
                      f"median {cover.median():.0%}, min {cover.min():.0%}, max {cover.max():.0%}. "
                      "The monitored fleet is not all of Türkiye's wind, so use it for forecast error, not totals.")
    report.append("")


def build_load_plan(report: list) -> None:
    lp = load_raw("load_plan", "date")
    if lp is None:
        return
    h = col(lp, "lep").sort_index()
    day = h.index.tz_convert(TZ).tz_localize(None).normalize()
    daily = pd.DataFrame({"load_plan_mwh": h.groupby(day).sum(min_count=1),
                          "load_plan_peak_mw": h.groupby(day).max(), "hours": h.groupby(day).size()})
    daily.index.name = "date"
    core = OUT / "core_daily.csv"
    if core.exists():
        c = pd.read_csv(core, parse_dates=["date"]).set_index("date")
        daily["consumption_mwh"] = c["consumption_mwh"].reindex(daily.index)
        daily["plan_error_pct"] = (daily["load_plan_mwh"] / daily["consumption_mwh"] - 1) * 100
        daily.loc[daily["hours"] < 24, "plan_error_pct"] = float("nan")
    daily.round(3).to_csv(OUT / "load_plan_daily.csv")
    first, last = daily.index.min().date(), daily.index.max().date()
    short = daily[daily["hours"] < 24]
    report.append(f"## Load plan (load-plan)\n\n- Range: {first} to {last}, {len(daily)} days.\n"
                  f"- Days with fewer than 24 hours: {len(short)} ({spans([x.date() for x in short.index])}).")
    if "plan_error_pct" in daily:
        e = daily["plan_error_pct"].dropna()
        if len(e):
            report.append(f"- Plan versus real-time consumption, daily: median {e.median():+.1f}%, "
                          f"5th to 95th percentile {e.quantile(.05):+.1f}% to {e.quantile(.95):+.1f}%. "
                          "Real-time consumption includes unmetered embedded generation from 30 Dec 2020, so "
                          "compare periods on the same side of that date.")
    report.append("")


def build_line_events(report: list) -> None:
    ev = load_raw("line_events", "baslangicTarihi")
    if ev is None:
        return
    ev = ev.drop_duplicates()
    ev["start"] = pd.to_datetime(ev["baslangicTarihi"].astype(str) + " " + ev["baslangicSaati"].astype(str), errors="coerce")
    ev["end"] = pd.to_datetime(ev["bitisTarihi"].astype(str) + " " + ev["bitisSaati"].astype(str), errors="coerce")
    ev["hours"] = (ev["end"] - ev["start"]).dt.total_seconds() / 3600
    out = ev.rename(columns={"hatAdi": "line", "olayTuru": "type", "aciklama": "description"})[
        ["start", "end", "hours", "line", "type", "description"]].sort_values("start")
    out.assign(hours=out["hours"].round(2)).to_csv(OUT / "line_events.csv", index=False)
    report.append(f"## Interconnection line events\n\n- {len(out)} events from {out['start'].min():%Y-%m-%d} to "
                  f"{out['start'].max():%Y-%m-%d}; {int(out['end'].isna().sum())} without an end time.\n"
                  f"- Event types: {out['type'].value_counts().to_dict()}.\n")


def build_capacity(report: list) -> None:
    files = sorted((RAW / "ren_capacity").glob("*.csv"))
    if not files:
        return
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    kinds = {"Güneş": "solar", "Rüzgar": "wind", "Rezarvuarlı": "hydro_reservoir", "Kanal Tipi": "hydro_run_of_river",
             "Biyokütle": "biomass", "Jeotermal": "geothermal"}

    def slug(x: str) -> str:
        return kinds.get(x) or re.sub(r"\W+", "_", str(x).lower()).strip("_")

    df["kind"] = df["renewableEnergyType"].map(slug)
    df["month"] = pd.to_datetime(df["period"]).dt.strftime("%Y-%m")
    parts = []
    for col, tag in (("licencedCapacity", "licensed"), ("unlicencedCapacity", "unlicensed"), ("total", "total")):
        p = df.pivot_table(index="month", columns="kind", values=col, aggfunc="last")
        p.columns = [f"{k}_{tag}_mw" for k in p.columns]
        parts.append(p)
    wide = pd.concat(parts, axis=1).sort_index()
    wide.to_csv(OUT / "ren_capacity_monthly.csv")
    unknown = sorted(set(df["renewableEnergyType"]) - set(kinds))
    report.append(f"## YEKDEM installed capacity (ren-capacity)\n\n- Range: {wide.index.min()} to {wide.index.max()}, "
                  f"{len(wide)} months.\n- Source categories not renamed: {unknown}. Unit assumed MW.\n")
    if {"solar_unlicensed_mw", "solar_licensed_mw"}.issubset(wide.columns):
        last = wide.iloc[-1]
        report.append(f"- Latest month ({wide.index[-1]}): solar licensed {last['solar_licensed_mw']:,.0f} MW, "
                      f"unlicensed {last['solar_unlicensed_mw']:,.0f} MW.\n")


def build_ul_gen(report: list) -> None:
    u = load_raw("ul_gen", "date")
    if u is None:
        return
    names = {"toplam": "total", "ruzgar": "wind", "biyogaz": "biogas", "kanalTipi": "run_of_river",
             "biyokutle": "biomass", "gunes": "solar", "diger": "other"}
    h = pd.DataFrame({f"ul_{v}_mwh": col(u, k) for k, v in names.items()}).sort_index()
    h.index = h.index.tz_convert(TZ)
    day = h.index.tz_localize(None).normalize()
    daily = h.groupby(day).sum(min_count=1)
    daily["hours"] = h.groupby(day).size()
    daily.index.name = "date"
    daily.round(3).to_csv(OUT / "ul_gen_daily.csv")
    mkey = day.to_period("M").astype(str)
    mon = h.groupby(mkey).sum(min_count=1)
    mon["hours"] = h.groupby(mkey).size()
    mon.index.name = "month"
    mon.round(3).to_csv(OUT / "ul_gen_monthly.csv")

    first, last = daily.index.min().date(), daily.index.max().date()
    short = daily[daily["hours"] < 24]
    report.append(f"## YEKDEM unlicensed generation (ren-ul-gen)\n\n- Range: {first} to {last}, {len(daily)} days "
                  "(the newest months are published with a delay). Unit assumed MWh per hour.\n"
                  f"- Days with fewer than 24 hours: {len(short)} ({spans([x.date() for x in short.index])}).")
    parts = h[[c for c in h.columns if c != "ul_total_mwh"]].sum(axis=1)
    diff = (parts - h["ul_total_mwh"]).abs()
    report.append(f"- Sources add up to the published total (within 1 MWh) in {int((diff <= 1).sum())} of {int(diff.notna().sum())} hours.")
    hr = h.index.hour
    night = (hr >= 21) | (hr <= 3)
    sol = h["ul_solar_mwh"]
    if sol.sum() > 0:
        report.append(f"- Share of 'solar' energy booked between 21:00 and 03:59: {sol[night].sum() / sol.sum():.1%}. "
                      "Real solar output is zero at night, so a large share means the source labels are not reliable.")
    yearly = h.groupby(h.index.year)[["ul_total_mwh", "ul_solar_mwh", "ul_other_mwh"]].sum()
    lines = ["| Year | Total (GWh) | Solar share | 'Other' share |", "|---|---:|---:|---:|"]
    for y, r in yearly.iterrows():
        lines.append(f"| {y} | {r['ul_total_mwh'] / 1000:,.0f} | {r['ul_solar_mwh'] / r['ul_total_mwh']:.0%} | "
                     f"{r['ul_other_mwh'] / r['ul_total_mwh']:.0%} |")
    report.append("- Shares by year (this series covers only unlicensed plants inside YEKDEM, not all unlicensed plants):\n\n"
                  + "\n".join(lines) + "\n")


PROVINCE_FIX = {"AFYON": "AFYONKARAHİSAR"}


def build_congestion(report: list) -> None:
    files = sorted((RAW / "congestion").glob("*.csv"))
    if not files:
        return
    df = pd.concat((pd.read_csv(f).assign(month=f.stem) for f in files), ignore_index=True)
    df["province"] = df["cityName"].astype(str).str.strip().replace(PROVINCE_FIX)
    df["kind"] = df["price_type"].str.lower() + "_" + df["order_type"].str.replace("_REGULATION", "", regex=False).str.lower()
    df["cost"] = num(df["congestionCost"])
    prov = df.pivot_table(index=["month", "province"], columns="kind", values="cost", aggfunc="sum").reset_index()
    kinds = ["smp_up", "smp_down", "mcp_up", "mcp_down"]
    for k in kinds:
        if k not in prov:
            prov[k] = float("nan")
    prov["smp_total"] = prov["smp_up"] + prov["smp_down"]
    prov["mcp_total"] = prov["mcp_up"] + prov["mcp_down"]
    cols = kinds + ["smp_total", "mcp_total"]
    prov = prov[["month", "province"] + cols].rename(columns={c: f"{c}_tl" for c in cols})
    prov.round(0).to_csv(OUT / "congestion_province_monthly.csv", index=False)
    nat = prov.groupby("month")[[f"{c}_tl" for c in cols]].sum()
    nat.round(0).to_csv(OUT / "congestion_monthly.csv")

    nz = nat[nat["smp_total_tl"] > 0]
    yearly = nat.groupby(nat.index.str[:4])["smp_total_tl"].sum() / 1e6
    report.append(f"## Congestion cost by province (congestion-cost)\n\n- Range: {nat.index.min()} to {nat.index.max()}, "
                  f"{len(nat)} months; {len(nz)} months with a non-zero national total. Unit assumed TL.\n"
                  "- National total at SMP prices (up + down regulation), million TL per year: "
                  + ", ".join(f"{y}: {v:,.1f}" for y, v in yearly.items()) + ".")
    top = prov.groupby("province")["smp_total_tl"].sum().sort_values(ascending=False).head(6)
    report.append("- Largest provinces over the whole history (SMP, million TL): "
                  + ", ".join(f"{p} {v / 1e6:,.1f}" for p, v in top.items()) + ".")
    neg = int((df["cost"] < 0).sum())
    report.append(f"- Negative values: {neg}. Rows per month: {df.groupby('month').size().median():.0f} (median).")
    seen = df.groupby("province")["month"].nunique()
    odd = seen[seen < 0.9 * df["month"].nunique()]
    if len(odd):
        report.append("- Province names that appear in fewer than 90% of months (renamed or added over time): "
                      + ", ".join(f"{p} ({n})" for p, n in odd.sort_values().head(10).items()) + ".")
    report.append("")


def build_line_capacity(report: list) -> None:
    files = sorted((RAW / "line_capacity").glob("*.csv"))
    if not files:
        return
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601", errors="coerce").dt.tz_convert(TZ)
    df = df[df["time"].notna()]
    for c in ("totalCapacity", "availableCapacity"):
        df[c] = num(df[c])
    g = df.groupby(["direction", "time"])
    rows = g.size()
    conflict = g[["totalCapacity", "availableCapacity"]].nunique().max(axis=1) > 1
    df["date"] = df["time"].dt.tz_localize(None).dt.normalize()
    daily = df.groupby(["date", "direction"]).agg(total_mw=("totalCapacity", "mean"), available_mw=("availableCapacity", "mean"),
                                                  hours=("time", "nunique")).reset_index()
    daily.round({"total_mw": 2, "available_mw": 2}).to_csv(OUT / "line_capacity_daily.csv", index=False)
    report.append(f"## Interconnection line capacities (line-capacities)\n\n- Range: {daily['date'].min().date()} to "
                  f"{daily['date'].max().date()}. Unit assumed MW.\n"
                  f"- Rows per direction and hour, as {{rows: number of direction-hours}}: {rows.value_counts().sort_index().to_dict()}. "
                  f"Hours where the repeated rows disagree: {int(conflict.sum())}.")
    for dname, sub in daily.groupby("direction"):
        months = sorted(set(sub["date"].dt.strftime("%Y-%m")))
        full = pd.period_range(months[0], months[-1], freq="M").astype(str)
        gaps = [m for m in full if m not in set(months)]
        report.append(f"- {dname}: {months[0]} to {months[-1]}, months with no data: {len(gaps)}"
                      + (f" ({', '.join(gaps[:6])}{' ...' if len(gaps) > 6 else ''})." if gaps else ".")
                      + f" Total capacity values seen: {[float(x) for x in sorted(sub['total_mw'].round(0).unique())[:6]]}.")
    report.append("")


def build_reservoirs(report: list) -> None:
    p, q = OUT / "reservoirs_daily.csv", OUT / "reservoirs_info.csv"
    if not p.exists():
        return
    d = pd.read_csv(p, parse_dates=["date"])
    if not q.exists():
        report.append("## Reservoirs\n\n- reservoirs_info.csv not found, so no national fullness yet.\n")
        return
    info = pd.read_csv(q)
    if not {"max_volume", "min_volume"}.issubset(info.columns):
        report.append("## Reservoirs\n\n- Min and max volumes missing from reservoirs_info.csv; run fetch_extra.py again.\n")
        return
    d = d.merge(info[["dam_id", "max_volume", "min_volume"]], on="dam_id", how="left")
    d["usable_volume"] = d["max_volume"] - d["min_volume"]
    ok = d[(d["usable_volume"] > 0) & d["active_volume"].notna()]
    nat = ok.groupby("date").agg(dams=("dam_id", "nunique"), active_volume=("active_volume", "sum"),
                                 usable_volume=("usable_volume", "sum"))
    nat["fullness_pct"] = nat["active_volume"] / nat["usable_volume"] * 100
    nat.round(3).to_csv(OUT / "reservoirs_national_daily.csv")
    bas = ok.groupby(["date", "basin"]).agg(active_volume=("active_volume", "sum"), usable_volume=("usable_volume", "sum")).reset_index()
    bas["fullness_pct"] = bas["active_volume"] / bas["usable_volume"] * 100
    bas.round({"active_volume": 3, "usable_volume": 3, "fullness_pct": 3}).to_csv(OUT / "reservoirs_basin_daily.csv", index=False)

    chk = ok[ok["active_fullness_pct"] > 0]
    rel = ((chk["active_fullness_pct"] / 100 * chk["usable_volume"]) / chk["active_volume"] - 1).abs()
    latest = d["date"].max()
    n_latest = int((d["date"] == latest).sum())
    n_ok = int((ok["date"] == latest).sum())
    report.append(f"## Reservoirs (snapshots)\n\n- {d['date'].nunique()} daily snapshot(s) saved, first {d['date'].min().date()}, "
                  f"latest {latest.date()}: {n_latest} dams, {n_ok} with usable-volume information.\n"
                  f"- Check: active fullness x (max - min volume) matches active volume within 1% for "
                  f"{(rel <= .01).mean():.0%} of {len(rel)} dam-days. If this holds, fullness is the percent of usable storage.\n"
                  f"- National active volume {nat['active_volume'].iloc[-1]:,.0f} of {nat['usable_volume'].iloc[-1]:,.0f} usable "
                  f"(same unit as EPİAŞ's volumes, assumed million m3): {nat['fullness_pct'].iloc[-1]:.1f}% on {nat.index[-1].date()}.\n")


def write_report(report: list) -> None:
    head = ["# Quality report: extra EPİAŞ series", "",
            f"Written by `scripts/fetch_extra.py`. Latest run: {pd.Timestamp.now(TZ):%Y-%m-%d %H:%M}.", ""]
    body = report + (["## Notes from the run", ""] + [f"- {n}" for n in notes] if notes else [])
    (OUT / "quality_report_extra.md").write_text("\n".join(head + body) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2011-11-01", help="earliest month to look for (each series starts when its data does)")
    ap.add_argument("--end", default=str(date.today() - timedelta(days=1)))
    ap.add_argument("--refresh-months", type=int, default=2)
    ap.add_argument("--only", default="", help="download only series whose name contains this text")
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    OUT.mkdir(parents=True, exist_ok=True)
    if not args.skip_download:
        eptr = fc.connect()
        print("Downloading")
        download(eptr, start, end, args.refresh_months, args.only)
        if not args.only or "reserv" in args.only.lower():
            snapshot_reservoirs(eptr)

    print("Building processed files")
    report: list = []
    for step in (build_gas, build_balancing, build_wind, build_load_plan, build_ul_gen, build_congestion,
                 build_line_capacity, build_line_events, build_capacity, build_reservoirs):
        try:
            step(report)
        except Exception as exc:  # a broken series must not stop the others
            notes.append(f"{step.__name__} failed: {type(exc).__name__}: {exc}")
    write_report(report)
    print(f"Done. Quality report: {OUT / 'quality_report_extra.md'}")
    for n in notes:
        print("  note:", n)


if __name__ == "__main__":
    main()
