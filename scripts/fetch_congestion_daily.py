"""
Congestion cost by province, one day at a time.

Why: the monthly congestion totals jumped from about 0.3 billion TL (2025) to 16.5 billion TL (2026), almost all of it
in March to June. EPİAŞ returns one total per province for the whole window, so a daily series needs one call per day.
With a daily series we can compare the cost with the same day's price, zero-price hours, solar, wind, hydro and gas.

What it writes
  data/raw/congestion_daily/<YYYY-MM>.csv      data as EPİAŞ returns it (local only, never committed)
  data/raw/congestion_daily/_done.txt          which day and price/order type were already downloaded (so a run can resume)
  data/processed/congestion_daily.csv          one row per day and province: smp_up_tl, smp_down_tl (and mcp_* with --with-mcp)

Usage (credentials come from EPTR_USERNAME and EPTR_PASSWORD, as for the other scripts)
  python scripts/fetch_congestion_daily.py                              # 2026-02-01 to 2026-08-31, SMP up and down
  python scripts/fetch_congestion_daily.py --start 2026-01-01 --end 2026-10-14
  python scripts/fetch_congestion_daily.py --also-last-year             # same dates one year earlier, for comparison
  python scripts/fetch_congestion_daily.py --with-mcp                   # also the PTF (MCP) price basis
  python scripts/fetch_congestion_daily.py --skip-download              # rebuild the processed file only
  python scripts/fetch_congestion_daily.py --skip-download --deconvolve # data downloaded by the first version (see below)

End date: EPİAŞ includes the whole end date, so a window d..d+1 returns two days. The first version of this script asked
for d..d+1 and every daily value is therefore the cost of day d plus day d+1. --deconvolve undoes that without a new
download: cost(d) = value(d) - cost(d+1), worked backwards inside each run of consecutive days. Use it only on raw files
made with the first version; new downloads ask for d..d and need no correction.

Roughly 2 calls per day (4 with --with-mcp). Seven months take about 10 to 15 minutes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_extra as fx  # noqa: E402  (connection, call_x, province names)

RAW_DIR = fx.RAW / "congestion_daily"
OUT = fx.OUT
KEY = "congestion-cost"


def variants(with_mcp: bool) -> list[dict]:
    prices = ("SMP", "MCP") if with_mcp else ("SMP",)
    return [dict(price_type=p, order_type=o) for p in prices for o in ("UP_REGULATION", "DOWN_REGULATION")]


def tag(v: dict) -> str:
    return f"{v['price_type']}_{v['order_type']}"


def end_is_included() -> bool:
    """The end date IS included (daily windows d..d+1 added up to twice the monthly totals). If the test has not
    been run yet, assume so; a day is then requested as d..d, never d..d+1."""
    marker = fx.RAW / "congestion" / "_end_inclusive_v2.txt"
    return not (marker.exists() and marker.read_text().strip() == "no")


def load_done() -> set[str]:
    f = RAW_DIR / "_done.txt"
    return set(f.read_text().split("\n")) - {""} if f.exists() else set()


def download(eptr, days: list[date], vs: list[dict]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    done = load_done()
    inclusive = end_is_included()
    problems: list[str] = []
    n_new = 0
    for d in days:
        for v in vs:
            key = f"{d.isoformat()}|{tag(v)}"
            if key in done:
                continue
            end = d if inclusive else d + timedelta(days=1)
            try:
                df = fx.call_x(eptr, KEY, d.isoformat(), end.isoformat(), v)
            except Exception as exc:  # one bad day must not stop the run
                problems.append(f"{key}: {exc}")
                continue
            if len(df):
                df = df.assign(date=d.isoformat(), price_type=v["price_type"], order_type=v["order_type"])
                path = RAW_DIR / f"{d:%Y-%m}.csv"
                df.to_csv(path, mode="a", header=not path.exists(), index=False)
            with open(RAW_DIR / "_done.txt", "a", encoding="utf-8") as fh:
                fh.write(key + "\n")
            done.add(key)
            n_new += 1
        if d.day == 1 or d == days[-1]:
            print(f"  downloaded up to {d} ({n_new} new calls)")
    for p in problems[:10]:
        print("  problem:", p)
    if problems:
        print(f"  {len(problems)} calls failed; run the script again to retry them.")


def undo_double_count(wide: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Value(d) = cost(d) + cost(d+1) -> cost(d), per province, inside each run of consecutive days."""
    wide = wide.copy()
    wide["date"] = pd.to_datetime(wide["date"])
    done = load_done()  # days that were asked for; a day with no row in the data is a day with zero cost
    asked = {k.split("|")[0] for k in done}
    days = pd.DatetimeIndex(sorted(set(pd.to_datetime(list(asked))) | set(wide["date"]))) if asked else \
        pd.DatetimeIndex(sorted(wide["date"].unique()))
    run = (days.to_series().diff() != pd.Timedelta(days=1)).cumsum().values
    runs = [days[run == r] for r in sorted(set(run))]
    parts = []
    for prov, g in wide.groupby("province"):
        g = g.set_index("date")
        for rd in runs:
            h = g.reindex(rd)[cols].fillna(0.0)
            vals = h.values.copy()
            nxt = [0.0] * len(cols)
            for i in range(len(vals) - 1, -1, -1):
                vals[i] = vals[i] - nxt
                nxt = vals[i].copy()
            out = pd.DataFrame(vals, index=rd, columns=cols)
            out["province"] = prov
            parts.append(out.reset_index().rename(columns={"index": "date"}))
    res = pd.concat(parts, ignore_index=True)
    res[cols] = res[cols].clip(lower=0.0)  # tiny negatives come from revisions between calls
    res["date"] = res["date"].dt.strftime("%Y-%m-%d")
    return res[(res[cols].abs().sum(axis=1) > 0)]


def build(deconvolve: bool = False) -> None:
    files = sorted(RAW_DIR.glob("*.csv"))
    if not files:
        print("No daily congestion data found.")
        return
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    df["province"] = df["cityName"].astype(str).str.strip().replace(fx.PROVINCE_FIX)
    df["kind"] = df["price_type"].str.lower() + "_" + df["order_type"].str.replace("_REGULATION", "", regex=False).str.lower()
    df["cost"] = pd.to_numeric(df["congestionCost"], errors="coerce")
    wide = df.pivot_table(index=["date", "province"], columns="kind", values="cost", aggfunc="sum").reset_index()
    for k in ("smp_up", "smp_down"):
        if k not in wide:
            wide[k] = float("nan")
    if deconvolve:
        cols = [c for c in wide.columns if c not in ("date", "province")]
        wide = undo_double_count(wide, cols)
        print("  each value was the cost of the day plus the next day; corrected to one day.")
    wide["smp_total"] = wide["smp_up"].fillna(0) + wide["smp_down"].fillna(0)
    wide = wide.rename(columns={c: f"{c}_tl" for c in wide.columns if c not in ("date", "province")})
    wide = wide.sort_values(["date", "province"]).round(0)
    OUT.mkdir(parents=True, exist_ok=True)
    wide.to_csv(OUT / "congestion_daily.csv", index=False)
    nat = wide.groupby("date")["smp_total_tl"].sum() / 1e6
    print(f"Wrote {OUT / 'congestion_daily.csv'}: {wide['date'].nunique()} days, {wide['province'].nunique()} provinces.")
    print(f"National SMP total, million TL: first day {nat.index.min()}, last day {nat.index.max()}, sum {nat.sum():,.0f}, "
          f"largest day {nat.idxmax()} ({nat.max():,.0f}).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-02-01")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--also-last-year", action="store_true", help="also download the same dates one year earlier")
    ap.add_argument("--with-mcp", action="store_true", help="also the PTF (MCP) price basis")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--deconvolve", action="store_true", help="correct raw files made by the first version (value = day + next day)")
    args = ap.parse_args()
    a, b = date.fromisoformat(args.start), date.fromisoformat(args.end)
    days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
    if args.also_last_year:
        earlier = []
        for d in days:
            try:
                earlier.append(d.replace(year=d.year - 1))
            except ValueError:  # 29 February
                pass
        days = sorted(set(days + earlier))
    if not args.skip_download:
        eptr = fx.fc.connect()
        fx.congestion_end_inclusive(eptr)  # tests once on real data and saves the answer
        print("Downloading")
        download(eptr, days, variants(args.with_mcp))
    print("Building the processed file")
    build(args.deconvolve)


if __name__ == "__main__":
    main()
