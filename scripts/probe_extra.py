"""
Probe the EPİAŞ calls we may add next (congestion, balancing detail, wind forecast,
unlicensed generation, load plan, reservoirs, interconnection lines, gas prices).

It downloads a SHORT window for each call, prints the columns and the first rows, and saves
the sample under data/raw/_probe/. Nothing here goes into the website. Read the output, then
we write the real fetch for the calls that return what we need.

Usage (same credentials as fetch_core.py)
  python scripts/probe_extra.py                       # 3 days ending 3 days ago
  python scripts/probe_extra.py --start 2026-09-01 --end 2026-09-03
  python scripts/probe_extra.py --only congestion     # run calls whose label contains this text

Paste the whole printout back to Claude (it is also saved as data/raw/_probe/probe_report.txt).
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import traceback
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "_probe"

# (label, eptr key, extra parameters, needs_dates)
CALLS = [
    ("congestion SMP up", "congestion-cost", {"price_type": "SMP", "order_type": "UP_REGULATION"}, True),
    ("congestion SMP down", "congestion-cost", {"price_type": "SMP", "order_type": "DOWN_REGULATION"}, True),
    ("congestion MCP both", "congestion-cost", {"price_type": "MCP", "order_type": "BOTH_REGULATIONS"}, True),
    ("balancing up (bpm-up)", "bpm-up", {}, True),
    ("balancing down (bpm-down)", "bpm-down", {}, True),
    ("wind forecast", "wind-forecast", {}, True),
    ("unlicensed generation", "ren-ul-gen", {}, True),
    ("load plan", "load-plan", {}, True),
    ("reservoir active fullness", "dams-active-fullness", {}, False),
    ("reservoir active volume", "dams-active-volume", {}, False),
    ("reservoir daily level", "dams-daily-level", {}, False),
    ("reservoir active fullness with dates", "dams-active-fullness", {"_dates": True}, False),
    ("reservoir daily volume", "dams-daily-volume", {}, False),
    ("reservoir water-energy provision", "dams-water-energy-provision", {}, False),
    ("reservoir info", "dams-info", {}, False),
    ("YEKDEM capacity period 2026-09", "ren-capacity", {"period": "2026-09-01"}, False),
    ("YEKDEM capacity period 2026-09 (month only)", "ren-capacity", {"period": "2026-09"}, False),
    ("interconnection direction list", "intl-capacity-demand-direction-list", {}, False),
    ("interconnection line capacity TRGR", "line-capacities", {"intl_direction": "TRGR"}, True),
    ("interconnection line capacity GRTR", "line-capacities", {"intl_direction": "GRTR"}, True),
    ("interconnection line capacity TRBG", "line-capacities", {"intl_direction": "TRBG"}, True),
    ("interconnection line capacity BGTR", "line-capacities", {"intl_direction": "BGTR"}, True),
    ("capacity auction requests TRGR", "capacity-demand", {"intl_direction": "TRGR"}, True),
    ("interconnection line events", "international-line-events", {}, True),
    ("gas spot prices (SGP)", "ng-spot-prices", {}, True),
    ("gas balancing price (BGP)", "ng-balancing-price", {}, True),
]


def connect():
    from eptr2 import EPTR2

    user, pwd = os.environ.get("EPTR_USERNAME"), os.environ.get("EPTR_PASSWORD")
    if not user or not pwd:
        sys.exit("Set EPTR_USERNAME and EPTR_PASSWORD first (Colab Secrets).")
    return EPTR2(username=user, password=pwd, use_dotenv=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    default_end = date.today() - timedelta(days=3)
    ap.add_argument("--start", default=str(default_end - timedelta(days=2)))
    ap.add_argument("--end", default=str(default_end))
    ap.add_argument("--only", default="", help="run only calls whose label contains this text")
    args = ap.parse_args()
    # EPİAŞ refuses ranges longer than one year; a probe only needs a few days
    s, e = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if (e - s).days > 14:
        s = e - timedelta(days=2)
        print(f"Window shortened to {s} .. {e} (EPİAŞ allows at most 1 year; a probe needs 3 days)")
    args.start, args.end = str(s), str(e)

    OUT.mkdir(parents=True, exist_ok=True)
    eptr = connect()
    buf = io.StringIO()
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_colwidth", 30)

    def say(text: str = "") -> None:
        print(text)
        buf.write(text + "\n")

    say(f"Probe window {args.start} to {args.end}")
    for label, key, extra, needs_dates in CALLS:
        if args.only and args.only.lower() not in label.lower():
            continue
        say("\n" + "=" * 78)
        say(f"{label}   [{key} {extra}]")
        try:
            kwargs = dict(extra)
            if kwargs.pop("_dates", False):
                needs_dates = True
            if needs_dates:
                kwargs.update(start_date=args.start, end_date=args.end)
            df = eptr.call(key, **kwargs)
            df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        except Exception as exc:
            say(f"FAILED: {type(exc).__name__}: {str(exc)[:300]}")
            say(traceback.format_exc(limit=1)[-300:])
            continue
        say(f"rows: {len(df)}   columns: {list(df.columns)}")
        if len(df):
            say("dtypes: " + ", ".join(f"{c}={t}" for c, t in df.dtypes.astype(str).items()))
            with redirect_stdout(io.StringIO()) as tmp:
                print(df.head(6).to_string())
            say(tmp.getvalue())
            safe = "".join(ch if ch.isalnum() else "_" for ch in label)
            df.head(500).to_csv(OUT / f"{safe}.csv", index=False)

    (OUT / "probe_report.txt").write_text(buf.getvalue(), encoding="utf-8")
    print(f"\nSaved the report and samples under {OUT}")


if __name__ == "__main__":
    main()
