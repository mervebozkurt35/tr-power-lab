"""
Daily update of the processed data files from EPİAŞ.

The full downloaders (fetch_core.py, fetch_extra.py) keep every raw hourly file on a disk and rebuild all
processed files from them. The raw files are not in the repository, so a scheduled job cannot do that. This
script does the daily work from the processed files alone:

  1. download only the last N months (default 2) plus one earlier month of context into a temporary folder,
  2. build the processed files from that short window with the same code as the full run,
  3. replace the matching rows in data/processed/*.csv and append the new days; older rows are never touched,
  4. check the result and write data/processed/update_status.json (what the pages show as "data through").

Why months and not just "yesterday": EPİAŞ revises recent values (PTF objections, real-time generation and
consumption corrections, the gas day-after price), so the whole current and previous month are refreshed every
day. The extra month before them is only context for features that look at neighbouring days; it is not written.

A file is replaced only when its checks pass. If a series fails, the old rows stay, the problem is listed in
update_status.json and in the job summary, and the script exits with an error so GitHub sends an email.

Reservoirs: EPİAŞ returns only the latest day, so the snapshot is added to reservoirs_daily.csv on every run.
This is the only copy of that history. It runs first, before anything that could fail.

Usage (credentials come from EPTR_USERNAME and EPTR_PASSWORD)
  python scripts/update_data.py                    # normal daily run
  python scripts/update_data.py --deep             # refresh the last 6 months (monthly run)
  python scripts/update_data.py --target DIR       # write to another folder than data/processed (for tests)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_core as fc  # noqa: E402
import fetch_extra as fx  # noqa: E402

TZ = fc.TZ
REAL_OUT = fc.OUT

# file -> (series group, time column, key columns, allow columns to be missing in the new build)
FILES = {
    "core_daily.csv": ("core", "date", ["date"], False),
    "core_monthly.csv": ("core", "month", ["month"], False),
    "gas_daily.csv": ("gas", "date", ["date"], False),
    "gas_monthly.csv": ("gas", "month", ["month"], False),
    "balancing_daily.csv": ("balancing", "date", ["date"], False),
    "balancing_monthly.csv": ("balancing", "month", ["month"], False),
    "wind_daily.csv": ("wind", "date", ["date"], False),
    "load_plan_daily.csv": ("load_plan", "date", ["date"], False),
    "ul_gen_daily.csv": ("ul_gen", "date", ["date"], False),
    "ul_gen_monthly.csv": ("ul_gen", "month", ["month"], False),
    "congestion_monthly.csv": ("congestion", "month", ["month"], False),
    "congestion_province_monthly.csv": ("congestion", "month", ["month", "province"], False),
    "line_capacity_daily.csv": ("line_capacity", "date", ["date", "direction"], False),
    "line_events.csv": ("line_events", "start", ["start", "line", "type"], False),
    "ren_capacity_monthly.csv": ("ren_capacity", "month", ["month"], True),
}

# raw series each group is built from (names in fetch_core.SERIES and fetch_extra.SERIES)
GROUP_SERIES = {
    "gas": ["gas_spot", "gas_balancing", "gas_direction", "gas_imbalance", "gas_match", "gas_trade", "gas_physical"],
    "balancing": ["bpm_up", "bpm_down"],
    "wind": ["wind"], "load_plan": ["load_plan"], "ul_gen": ["ul_gen"], "congestion": ["congestion"],
    "line_capacity": ["line_capacity"], "line_events": ["line_events"], "ren_capacity": ["ren_capacity"],
}
BUILDERS = {
    "gas": fx.build_gas, "balancing": fx.build_balancing, "wind": fx.build_wind, "load_plan": fx.build_load_plan,
    "ul_gen": fx.build_ul_gen, "congestion": fx.build_congestion, "line_capacity": fx.build_line_capacity,
    "line_events": fx.build_line_events, "ren_capacity": fx.build_capacity,
}
# how many days the newest day of a file may lag behind yesterday before it is reported (None: not checked)
MAX_LAG = {"core_daily.csv": 1, "gas_daily.csv": 3, "balancing_daily.csv": 3, "wind_daily.csv": 3,
           "load_plan_daily.csv": 1, "line_capacity_daily.csv": 5}
FATAL_LAG = {"core_daily.csv"}  # a lag beyond MAX_LAG is an error, not a warning

status: dict = {"files": {}, "warnings": [], "errors": []}


def warn(msg: str) -> None:
    print("  WARNING:", msg)
    status["warnings"].append(msg)


def fail(msg: str) -> None:
    print("  ERROR:", msg)
    status["errors"].append(msg)


# ---------------------------------------------------------------- windows

def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def last_day_in(path: Path, col: str) -> date | None:
    if not path.exists():
        return None
    s = pd.read_csv(path, usecols=[col], dtype=str)[col].dropna()
    s = s[s != ""]
    if s.empty:
        return None
    return pd.to_datetime(s.max()[:10], errors="coerce").date()


# ---------------------------------------------------------------- download

def download_core(eptr, ctx_start: date, end: date) -> bool:
    """Short window of the core hourly series into the temporary raw folder. True if all required months arrived."""
    ok = True
    months = list(fc.month_ranges(ctx_start, end))
    for series, (_key, fetch) in fc.SERIES.items():
        folder = fc.RAW / series
        folder.mkdir(parents=True, exist_ok=True)
        for a, b in months:
            tag = a.strftime("%Y-%m")
            try:
                df = fc.fetch_month(eptr, fetch, a, b)
            except Exception as exc:
                fail(f"core: {series} {tag} could not be downloaded ({exc})")
                ok = ok and series in fc.OPTIONAL
                continue
            if df.empty:
                fail(f"core: {series} {tag} returned no data")
                ok = ok and series in fc.OPTIONAL
                continue
            df.to_csv(folder / f"{tag}.csv", index=False)
            print(f"  {series:14s} {tag}  {len(df):6d} rows")
    try:
        fc.download_euas(eptr, ctx_start, end)
    except Exception as exc:
        warn(f"core: bilateral_euas could not be downloaded ({exc})")
    return ok


def download_extra(eptr, series_from: dict, end: date) -> None:
    for name, spec in fx.SERIES.items():
        first = series_from.get(name)
        if first is None:
            continue
        folder = fc.RAW / name
        folder.mkdir(parents=True, exist_ok=True)
        got = 0
        for a, b in fc.month_ranges(first, end):
            tag = a.strftime("%Y-%m")
            try:
                df = fx.fetch_month(eptr, spec, a, b)
            except Exception as exc:
                fail(f"{name}: {tag} could not be downloaded ({exc})")
                continue
            if df.empty:
                if spec["dense"] and not spec.get("lag"):
                    warn(f"{name}: no data returned for {tag}")
                continue
            df.to_csv(folder / f"{tag}.csv", index=False)
            got += 1
            print(f"  {name:14s} {tag}  {len(df):6d} rows")
        if not got:
            print(f"  {name:14s} nothing new")


# ---------------------------------------------------------------- merge

def read_text(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


REVISION_BUCKETS = [("to_3d", 0, 3), ("4_14d", 4, 14), ("15_31d", 15, 31), ("32_62d", 32, 62), ("over_62d", 63, 10**6)]


def log_revisions(target: Path, name: str, end: date, ages: pd.Series) -> None:
    """Append how old the revised days were, so the refresh window can be set from evidence.
    A day revised 1-3 days after the fact is normal (the last hours arrive late); older revisions are the ones the window is for."""
    row = {"run_end": end.isoformat(), "file": name, "revised_days": len(ages), "oldest_age_days": int(ages.max())}
    for label, lo, hi in REVISION_BUCKETS:
        row[label] = int(((ages >= lo) & (ages <= hi)).sum())
    path = target / "revision_log.csv"
    pd.DataFrame([row]).to_csv(path, mode="a", header=not path.exists(), index=False)
    status["files"][name]["revised_by_age"] = {k: row[k] for k, _, _ in REVISION_BUCKETS}


def merge_file(name: str, target: Path, tmp_out: Path, window_from: date, end: date) -> bool:
    """Replace the rows of `name` from window_from on with the new build, keep everything older as it is."""
    group, tcol, keys, allow_missing = FILES[name]
    info = status["files"].setdefault(name, {})
    new_path, old_path = tmp_out / name, target / name
    if not new_path.exists():
        info.update(level="warn", message="no output from the short build; file left as it was")
        warn(f"{name}: no output from the short build; file left as it was")
        return False
    new, old = read_text(new_path), (read_text(old_path) if old_path.exists() else None)
    if tcol not in new.columns:
        info.update(level="error", message=f"time column `{tcol}` missing in the new build")
        fail(f"{name}: time column `{tcol}` missing in the new build; file left as it was")
        return False

    # the new rows that belong to the window (the context month before it is not written)
    cut = window_from.isoformat() if tcol in ("date", "start") else window_from.strftime("%Y-%m")
    new = new[new[tcol] >= cut].copy()
    if new.empty:
        info.update(level="warn", message="no new rows in the window")
        warn(f"{name}: no new rows in the window")
        return False

    if old is None:
        merged = new
        added, changed = len(new), 0
        rev_ages = None
    else:
        rev_ages = None
        missing = [c for c in old.columns if c not in new.columns]
        if missing and len(missing) >= len([c for c in old.columns if c not in keys]):
            info.update(level="error", message="none of the data columns are in the new build")
            fail(f"{name}: none of the data columns are in the new build. File left as it was.")
            return False
        if missing and not allow_missing:
            # a series that failed to download leaves its columns out: new days stay blank there until a later run
            warn(f"{name}: columns missing in the new build, left blank for new days: {missing}")
        for c in missing:
            new[c] = ""
        k_new = new[keys].agg("|".join, axis=1)
        k_old = old[keys].agg("|".join, axis=1)
        if k_new.duplicated().any() and name != "line_events.csv":
            info.update(level="error", message="duplicate keys in the new build")
            fail(f"{name}: duplicate keys in the new build. File left as it was.")
            return False
        drop = k_old.isin(set(k_new))     # old rows that the new build replaces
        kept = old[~drop]
        if name == "line_events.csv":
            # an event keeps its start, but its end can be filled in later: all rows of the same events are replaced
            added = int(k_new[~k_new.isin(set(k_old))].nunique())
            seen = old[drop].merge(new, how="left", indicator=True, on=list(old.columns))
            changed = int((seen["_merge"] == "left_only").sum())
        else:
            added = int((~k_new.isin(set(k_old))).sum())
            cols = [c for c in old.columns if c not in keys]
            # a value that was there and now comes back empty is treated as a failed download, not as a revision
            ni, oi = new.set_index(keys), old.set_index(keys)
            common = ni.index.intersection(oi.index)
            lost = 0
            for c in cols:
                if c in ni.columns and len(common):
                    n_c, o_c = ni.loc[common, c], oi.loc[common, c]
                    gone = (n_c == "") & (o_c != "")
                    if gone.any():
                        lost += int(gone.sum())
                        ni.loc[gone[gone].index, c] = o_c[gone]
            if lost:
                warn(f"{name}: {lost} value(s) came back empty where the file had a value; the old value was kept")
                new = ni.reset_index()[list(new.columns)]
            both = old[drop].merge(new, on=keys, suffixes=("_old", "_new"))
            changed = 0
            if len(both) and cols:
                diff = pd.Series(False, index=both.index)
                for c in cols:
                    diff |= both[f"{c}_old"] != both[f"{c}_new"]
                changed = int(diff.sum())
                if tcol == "date" and changed:
                    rev_ages = (pd.Timestamp(end) - pd.to_datetime(both.loc[diff, tcol])).dt.days
                if name == "core_daily.csv" and changed:
                    for c in ("ptf_mean", "consumption_mwh"):
                        x = pd.to_numeric(both[f"{c}_old"], errors="coerce")
                        y = pd.to_numeric(both[f"{c}_new"], errors="coerce")
                        rel = ((y - x).abs() / x.abs().where(x.abs() > 0)).dropna()
                        if len(rel) and rel.max() > 0.25:
                            warn(f"{name}: {c} was revised by more than 25% on {int((rel > 0.25).sum())} day(s), "
                                 f"largest {rel.max():.0%}")
        extra_cols = [c for c in new.columns if c not in old.columns]
        merged = pd.concat([kept, new[[c for c in old.columns if c in new.columns] + extra_cols]], ignore_index=True)
        merged = merged.reindex(columns=list(old.columns) + extra_cols).fillna("")
        merged = merged.sort_values(["start"] if name == "line_events.csv" else keys, kind="stable").reset_index(drop=True)
        if extra_cols:
            warn(f"{name}: new columns added: {extra_cols}")

    # ---- checks on the merged file
    problems = check_file(name, merged, tcol, old, end)
    if problems:
        info.update(level="error", message="; ".join(problems))
        for p in problems:
            fail(f"{name}: {p}. File left as it was.")
        return False

    tmp = old_path.with_suffix(".csv.tmp")
    merged.to_csv(tmp, index=False)
    os.replace(tmp, old_path)
    if rev_ages is not None:
        log_revisions(target, name, end, rev_ages)
    last = merged[tcol].max()
    info.update(level="ok", rows=len(merged), added=added, changed=changed, last=str(last)[:10] if tcol != "month" else str(last))
    print(f"  {name:34s} +{added:4d} rows, {changed:4d} revised, last {info['last']}")

    lag_limit = MAX_LAG.get(name)
    if lag_limit is not None and tcol == "date":
        lag = (end - pd.to_datetime(str(last)[:10]).date()).days
        info["lag_days"] = lag
        if lag > lag_limit:
            (fail if name in FATAL_LAG else warn)(f"{name}: newest day is {last}, {lag} days behind yesterday")
    return True


def check_file(name: str, merged: pd.DataFrame, tcol: str, old: pd.DataFrame | None, end: date) -> list[str]:
    problems = []
    if old is not None and len(merged) < len(old):
        problems.append(f"merge would drop rows ({len(old)} to {len(merged)})")
    if name == "core_daily.csv":
        recent = merged[merged["date"] >= (end - timedelta(days=45)).isoformat()].copy()
        for c in ("ptf_mean", "ptf_max", "ptf_min", "consumption_mwh", "hours_with_price", "ptf_cap_tl_mwh"):
            recent[c] = pd.to_numeric(recent.get(c), errors="coerce")
        if (recent["ptf_min"] < -1).any():
            warn(f"{name}: negative PTF in the recent days; check against the platform")
        capped = recent["ptf_cap_tl_mwh"].notna()
        if (recent.loc[capped, "ptf_max"] > recent.loc[capped, "ptf_cap_tl_mwh"] + 1).any():
            warn(f"{name}: PTF above the cap in data/price_caps.csv in the recent days; the cap table may need a new row")
        if (recent["hours_with_price"] > 25).any():
            problems.append("more than 25 hourly prices on a day")
        base = pd.to_numeric(merged["consumption_mwh"], errors="coerce")
        base = base[merged["date"] < (end - timedelta(days=45)).isoformat()].tail(60)
        med = base.median()
        if pd.notna(med) and med > 0:
            full = recent[recent["hours_with_price"] >= 23]["consumption_mwh"].dropna()
            if ((full < 0.4 * med) | (full > 2.5 * med)).any():
                problems.append("daily consumption outside 0.4 to 2.5 times its recent median")
        last = recent[recent["hours_with_price"] > 0].tail(1)
        if len(last) and float(last["hours_with_price"].iloc[0]) < 23:
            warn(f"{name}: newest day {last['date'].iloc[0]} has only {int(last['hours_with_price'].iloc[0])} hourly prices")
    return problems


# ---------------------------------------------------------------- main

def write_status(target: Path, end: date, through: dict) -> None:
    now = datetime.now(tz=pd.Timestamp.now(tz=TZ).tz)
    status.update(checked=pd.Timestamp.now(tz=TZ).strftime("%Y-%m-%d %H:%M"), timezone=TZ, yesterday=end.isoformat(),
                  data_through=through, ok=not status["errors"])
    (target / "update_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def step_summary(end: date) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["## Data update", "", f"Window ends {end.isoformat()}. Result: **{'ok' if not status['errors'] else 'errors'}**", "",
             "| File | Result | Rows added | Revised | Newest |", "|---|---|---:|---:|---|"]
    for n, i in status["files"].items():
        lines.append(f"| {n} | {i.get('level', '')}{(': ' + i['message']) if i.get('message') else ''} | "
                     f"{i.get('added', '')} | {i.get('changed', '')} | {i.get('last', '')} |")
    for title, items in (("Errors", status["errors"]), ("Warnings", status["warnings"])):
        if items:
            lines += ["", f"### {title}", ""] + [f"- {x}" for x in items]
    text = "\n".join(lines) + "\n"
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh-months", type=int, default=2, help="months rewritten every run (current and previous)")
    ap.add_argument("--deep", action="store_true", help="refresh the last 6 months instead")
    ap.add_argument("--end", default=None, help="last day to fetch, default yesterday (Istanbul)")
    ap.add_argument("--target", default=str(REAL_OUT), help="folder with the processed files to update")
    ap.add_argument("--work", default=None, help="folder for the temporary raw files (default: a new temp folder)")
    a = ap.parse_args()

    target = Path(a.target)
    end = date.fromisoformat(a.end) if a.end else pd.Timestamp.now(tz=TZ).date() - timedelta(days=1)
    n = 6 if a.deep else a.refresh_months
    # a gap since the last successful run widens the window so no day is skipped
    last_core = last_day_in(target / "core_daily.csv", "date")
    if last_core is not None:
        n = max(n, months_between(last_core.replace(day=1), end.replace(day=1)) + 1)
    this_month = end.replace(day=1)
    window_from = add_months(this_month, -(n - 1))
    ctx_start = add_months(window_from, -1)
    print(f"Window: rewrite from {window_from}, context from {ctx_start}, to {end}  ({n} months)")

    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="trpl_"))
    raw, out = work / "raw", work / "out"
    raw.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)

    # point both modules at the temporary folders; the reservoir steps use the real folder explicitly
    fc.RAW = fx.RAW = raw
    fc.OUT = fx.OUT = out
    (raw / "congestion").mkdir(parents=True, exist_ok=True)
    # congestion windows include their end date (observed October 2026); skip the long test on every run
    (raw / "congestion" / "_end_inclusive_v2.txt").write_text("yes")

    try:
        eptr = fc.connect()
    except SystemExit as exc:
        fail(str(exc))
        write_status(target, end, {})
        step_summary(end)
        return 1

    # ---- 1. reservoirs first: the history can only be built one day at a time
    fx.OUT = target
    try:
        fx.snapshot_reservoirs(eptr)
        rep: list = []
        fx.build_reservoirs(rep)
        status["files"]["reservoirs_daily.csv"] = {"level": "ok", "last": str(last_day_in(target / "reservoirs_daily.csv", "date"))}
    except Exception as exc:
        status["files"]["reservoirs_daily.csv"] = {"level": "error", "message": str(exc)}
        fail(f"reservoirs: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        fx.OUT = out
    for note in fx.notes:
        if note.startswith("reservoirs"):
            warn(note)
    fx.notes.clear()

    # ---- 2. core hourly series
    print("Core series")
    core_ok = False
    try:
        core_ok = download_core(eptr, ctx_start, end)
        if core_ok:
            fc.build(ctx_start, end)
    except SystemExit as exc:  # fetch_core uses sys.exit for fatal data problems
        core_ok = False
        fail(f"core: {exc}")
    except Exception as exc:
        core_ok = False
        fail(f"core: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    for note in fc.notes:
        status.setdefault("notes", []).append(note)
    if core_ok:
        if merge_file("core_daily.csv", target, out, window_from, end):
            merge_file("core_monthly.csv", target, out, window_from, end)
        else:  # the monthly file is built from the same hours, so it waits for the daily file
            status["files"]["core_monthly.csv"] = {"level": "error", "message": "skipped because core_daily.csv failed"}
            core_ok = False
    else:
        for name in ("core_daily.csv", "core_monthly.csv"):
            status["files"][name] = {"level": "error", "message": "core download or build failed; file left as it was"}
    if not core_ok and (target / "core_daily.csv").exists():
        # wind, the load plan and the gas exchange rates read core_daily.csv; give them the file that was accepted
        shutil.copy(target / "core_daily.csv", out / "core_daily.csv")

    # ---- 3. extra series (they read core_daily.csv from the short build, so core comes first)
    print("Extra series")
    floor_end = end.replace(day=1)
    series_from = {}
    for group, names in GROUP_SERIES.items():
        for s in names:
            series_from[s] = window_from
    series_from["ul_gen"] = add_months(floor_end, -(11 if a.deep else 7))   # published months late
    series_from["line_events"] = add_months(floor_end, -(23 if a.deep else 11))   # an open outage gets its end later
    series_from["ren_capacity"] = add_months(floor_end, -(5 if a.deep else 2))
    # context month for the series that look at neighbouring days
    for s in GROUP_SERIES["gas"] + ["wind", "load_plan", "bpm_up", "bpm_down"]:
        series_from[s] = ctx_start
    try:
        download_extra(eptr, series_from, end)
    except Exception as exc:
        fail(f"extra download: {type(exc).__name__}: {exc}")
        traceback.print_exc()

    window_for = {"ul_gen": series_from["ul_gen"], "line_events": series_from["line_events"],
                  "ren_capacity": series_from["ren_capacity"]}
    built = set()
    for group, build in BUILDERS.items():
        try:
            build([])
            built.add(group)
        except Exception as exc:
            fail(f"{group}: build failed: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    for note in fx.notes:
        status.setdefault("notes", []).append(note)

    stopped = set()
    for name, (group, *_rest) in FILES.items():
        if group == "core":
            continue
        if group not in built:
            status["files"].setdefault(name, {"level": "error", "message": "build failed; file left as it was"})
            continue
        if group in stopped:   # daily file failed: its monthly file waits too, so the two never disagree
            status["files"][name] = {"level": "error", "message": f"skipped because an earlier {group} file failed"}
            continue
        if not merge_file(name, target, out, window_for.get(group, window_from), end):
            stopped.add(group)

    # ---- 4. status
    through = {}
    for name, (group, tcol, *_r) in FILES.items():
        if tcol in ("date", "month"):
            d = last_day_in(target / name, tcol)
            if d is not None:
                through[name] = d.isoformat() if tcol == "date" else d.strftime("%Y-%m")
    write_status(target, end, through)
    step_summary(end)
    print("Errors:", len(status["errors"]), " warnings:", len(status["warnings"]))
    return 1 if status["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
