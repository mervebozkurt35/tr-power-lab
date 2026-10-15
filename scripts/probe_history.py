"""
Second probe: find out how far back each EPİAŞ call goes, and look again at the calls that came
back empty in the first probe (unlicensed generation, interconnection capacities).

Nothing here goes into the website. It prints short tables; paste the whole printout to Claude.
The report is also saved as data/raw/_probe/probe_history_report.txt.

Usage (same credentials as fetch_core.py)
  python scripts/probe_history.py
  python scripts/probe_history.py --only congestion      # run only the groups whose title contains this text
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import traceback
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "_probe"
warnings.filterwarnings("ignore")

# one early day per year-ish, to see where each call starts returning data
HISTORY_DAYS = ["2012-06-04", "2015-06-02", "2017-06-01", "2018-06-01", "2019-06-03", "2020-06-01",
                "2021-06-01", "2022-06-01", "2023-06-01", "2024-06-03", "2025-06-02", "2026-06-01"]
HISTORY_CALLS = [
    ("gas spot (SGP)", "ng-spot-prices", {}),
    ("gas balancing price", "ng-balancing-price", {}),
    ("balancing up", "bpm-up", {}),
    ("balancing down", "bpm-down", {}),
    ("wind forecast", "wind-forecast", {}),
    ("load plan", "load-plan", {}),
    ("unlicensed generation", "ren-ul-gen", {}),
    ("YEKDEM injection (licensed)", "ren-uevm", {}),
    ("line capacities TRGR", "line-capacities", {"intl_direction": "TRGR"}),
    ("pre-month capacity forecast", "tcat-pre-month-forecast", {}),
    ("nominal capacity", "nominal-capacity", {}),
    ("gas system direction", "ng-system-direction", {}),
    ("gas imbalance (system)", "ng-imbalance-system", {}),
]


def connect():
    from eptr2 import EPTR2

    user, pwd = os.environ.get("EPTR_USERNAME"), os.environ.get("EPTR_PASSWORD")
    if not user or not pwd:
        sys.exit("Set EPTR_USERNAME and EPTR_PASSWORD first (Colab Secrets).")
    return EPTR2(username=user, password=pwd, use_dotenv=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_colwidth", 28)
    eptr = connect()
    buf = io.StringIO()

    def say(text: str = "") -> None:
        print(text)
        buf.write(text + "\n")

    def run(key: str, **kw):
        df = eptr.call(key, **kw)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)

    def group(title: str) -> bool:
        if args.only and args.only.lower() not in title.lower():
            return False
        say("\n" + "=" * 78 + f"\n{title}")
        return True

    # 1. History depth: rows returned for one early day per year
    if group("HISTORY: rows returned for one day (2 days for calls that treat the end as exclusive)"):
        rows = []
        for label, key, extra in HISTORY_CALLS:
            line = {"call": label}
            for d in HISTORY_DAYS:
                end = (pd.Timestamp(d) + pd.Timedelta(days=1)).date().isoformat()
                try:
                    n = len(run(key, start_date=d, end_date=end, **extra))
                    line[d[:4] if d[5:7] == "06" else d] = n
                except Exception as exc:
                    line[d[:4]] = f"err:{type(exc).__name__}"
            rows.append(line)
        say(pd.DataFrame(rows).set_index("call").to_string())
        say("(a number is the row count for that day and the next; 0 = nothing published)")

    # 2. Unlicensed generation, again: older windows, one month
    if group("UNLICENSED GENERATION (ren-ul-gen), one week at a time"):
        for a, b in [("2026-09-01", "2026-09-07"), ("2026-06-01", "2026-06-07"), ("2025-06-01", "2025-06-07"),
                     ("2023-06-01", "2023-06-07")]:
            try:
                df = run("ren-ul-gen", start_date=a, end_date=b)
                say(f"{a}..{b}: rows {len(df)}  columns {list(df.columns)}")
                if len(df):
                    say(df.head(4).to_string())
            except Exception as exc:
                say(f"{a}..{b}: FAILED {type(exc).__name__}: {str(exc)[:200]}")

    # 3. Interconnections: which directions exist, and what the capacity calls return
    if group("INTERCONNECTION directions and capacities"):
        for key in ("intl-direction-list", "intl-capacity-demand-direction-list"):
            try:
                say(f"{key}: {run(key).iloc[:, 0].tolist()}")
            except Exception as exc:
                say(f"{key}: FAILED {type(exc).__name__}: {str(exc)[:200]}")
        dirs = []
        try:
            dirs = run("intl-direction-list").iloc[:, 0].astype(str).tolist()[:6]
        except Exception:
            pass
        for key, extra in [("line-capacities", {"intl_direction": d}) for d in dirs[:2]] + [
            ("tcat-pre-month-forecast", {}), ("tcat-pre-year-forecast", {}), ("nominal-capacity", {})]:
            for a, b in [("2026-09-01", "2026-09-03"), ("2025-06-01", "2025-06-03")]:
                try:
                    df = run(key, start_date=a, end_date=b, **extra)
                    say(f"{key} {extra} {a}..{b}: rows {len(df)}  columns {list(df.columns)}")
                    if len(df):
                        say(df.head(4).to_string())
                        break
                except Exception as exc:
                    say(f"{key} {extra} {a}..{b}: FAILED {type(exc).__name__}: {str(exc)[:200]}")

    # 4. Congestion cost: a whole month, every price and order type, to see non-zero values
    if group("CONGESTION COST by province, full months (top 6 provinces by cost)"):
        for a, b in [("2026-09-01", "2026-09-30"), ("2025-03-01", "2025-03-31"), ("2023-03-01", "2023-03-31")]:
            for pt in ("SMP", "MCP"):
                for ot in ("UP_REGULATION", "DOWN_REGULATION", "BOTH_REGULATIONS"):
                    try:
                        df = run("congestion-cost", start_date=a, end_date=b, price_type=pt, order_type=ot)
                        tot = pd.to_numeric(df["congestionCost"], errors="coerce").sum() if len(df) else 0
                        top = df.sort_values("congestionCost", ascending=False).head(6) if len(df) else df
                        say(f"{a[:7]} {pt:3s} {ot:17s} rows {len(df):3d} total {tot:,.0f}  top: "
                            + "; ".join(f"{r.cityName} {r.congestionCost:,.0f}" for r in top.itertuples()))
                    except Exception as exc:
                        say(f"{a[:7]} {pt} {ot}: FAILED {type(exc).__name__}: {str(exc)[:160]}")

    # 5. Gas: the other daily gas series that could sit next to the prices
    if group("GAS extras (3 days)"):
        for key in ("ng-system-direction", "ng-imbalance-system", "ng-daily-match-qty", "ng-daily-trade-volume",
                    "ng-total-trade-volume", "ng-physical-realization"):
            try:
                df = run(key, start_date="2026-10-08", end_date="2026-10-11")
                say(f"{key}: rows {len(df)}  columns {list(df.columns)}")
                if len(df):
                    say(df.head(3).to_string())
            except Exception as exc:
                say(f"{key}: FAILED {type(exc).__name__}: {str(exc)[:200]}")

    # 6. Reservoirs: reference tables, and whether any call accepts a date
    if group("RESERVOIR reference tables"):
        for key in ("dam-list", "basin-list", "dams-level-minmax", "dams-volume-minmax"):
            try:
                df = run(key)
                say(f"{key}: rows {len(df)}  columns {list(df.columns)}")
                if len(df):
                    say(df.head(4).to_string())
            except Exception as exc:
                say(f"{key}: FAILED {type(exc).__name__}: {str(exc)[:200]}")

    (OUT / "probe_history_report.txt").write_text(buf.getvalue(), encoding="utf-8")
    print(f"\nSaved the report under {OUT}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
