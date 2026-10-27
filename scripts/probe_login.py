"""One-off check: can this machine log in to the EPİAŞ Şeffaflık Platformu and download data?

Run it from GitHub Actions (workflow "EPİAŞ login test") or from Colab. It never prints the credentials.

What it does
  1. Prints the public IP address this run comes from (EPİAŞ asks web-service users to register their IP; this shows
     whether that matters from this machine).
  2. Checks that the login and data hosts can be reached, and how long a connection takes.
  3. Logs in (up to three tries) and downloads one day from a few calls: PTF, real-time consumption, spot gas prices and
     the reservoir snapshot (the only series that cannot be backfilled).
  4. Prints a short table and writes it to the GitHub step summary when run in Actions.

Exit code 1 if the login or the PTF call fails, so the workflow turns red; a failing extra call is only a warning.
Credentials come from the environment: EPTR_USERNAME and EPTR_PASSWORD.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from datetime import date, timedelta
from importlib.metadata import version

import pandas as pd

HOSTS = ["giris.epias.com.tr", "seffaflik.epias.com.tr"]
rows: list[tuple[str, str, str]] = []   # (step, result, detail)


def note(step: str, result: str, detail: str = "") -> None:
    rows.append((step, result, detail))
    print(f"[{result:>4}] {step}: {detail}")


def public_ip() -> str:
    import urllib.request
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
            return r.read().decode()
    except Exception as exc:
        return f"unknown ({type(exc).__name__})"


def check_host(host: str) -> None:
    t0 = time.time()
    try:
        with socket.create_connection((host, 443), timeout=15):
            note(f"connect {host}", "ok", f"{time.time() - t0:.1f} s")
    except Exception as exc:
        note(f"connect {host}", "FAIL", f"{type(exc).__name__}: {exc} after {time.time() - t0:.1f} s")


def main() -> int:
    user, pwd = os.environ.get("EPTR_USERNAME"), os.environ.get("EPTR_PASSWORD")
    if not user or not pwd:
        print("EPTR_USERNAME and EPTR_PASSWORD are not set (repository secrets).")
        return 1
    note("python / eptr2", "info", f"{sys.version.split()[0]} / eptr2 {version('eptr2')}")
    note("public IP of this run", "info", public_ip())
    for h in HOSTS:
        check_host(h)

    from eptr2 import EPTR2
    eptr, failed = None, False
    day = (date.today() - timedelta(days=2)).isoformat()     # two days back: certainly published
    nxt = (date.today() - timedelta(days=1)).isoformat()     # some calls need the end date one day later

    def timed(label: str, fn, critical: bool = False):
        nonlocal failed
        t0 = time.time()
        try:
            df = fn()
            df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
            note(label, "ok" if len(df) else "WARN", f"{len(df)} rows, {df.shape[1]} columns, {time.time() - t0:.1f} s")
            return df
        except Exception as exc:
            note(label, "FAIL" if critical else "WARN", f"{type(exc).__name__}: {str(exc)[:200]} after {time.time() - t0:.1f} s")
            failed = failed or critical
            return None

    for attempt in range(1, 4):
        t0 = time.time()
        try:
            eptr = EPTR2(username=user, password=pwd, use_dotenv=False)
            df = eptr.call("mcp", start_date=day, end_date=nxt)
            note(f"login and PTF, try {attempt}", "ok", f"{len(df)} rows, {time.time() - t0:.1f} s")
            break
        except Exception as exc:
            note(f"login and PTF, try {attempt}", "FAIL", f"{type(exc).__name__}: {str(exc)[:200]} after {time.time() - t0:.1f} s")
            eptr = None
            if attempt < 3:
                time.sleep(20)
    if eptr is None:
        failed = True
    else:
        timed("real-time consumption (rt-cons)", lambda: eptr.call("rt-cons", start_date=day, end_date=nxt))
        timed("spot gas prices (ng-spot-prices)", lambda: eptr.call("ng-spot-prices", start_date=day, end_date=nxt))
        timed("reservoir fullness (dams-active-fullness, latest day only)", lambda: eptr.call("dams-active-fullness"))

    summary = ["## EPİAŞ login test", "", "| Step | Result | Detail |", "|---|---|---|"]
    summary += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    summary += ["", "**Login worked from this machine.**" if not failed else "**Login or the PTF call failed.** See the rows above."]
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
