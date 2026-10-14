"""
Day-ahead (PTF) price limits in force on each day, from data/price_caps.csv.

Used by fetch_core.py (hours at the cap) and by the website pages (cap level, fallback counts).
The table starts on 1 April 2022. Before that the maximum followed a formula rather than a fixed
amount (three times the trailing twelve-month weighted average PTF, at most 2,000 TL/MWh, as
described in press reports of May 2022), so no hours-at-cap count is made for earlier dates.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CAPS_FILE = ROOT / "data" / "price_caps.csv"
TOLERANCE = 1.0   # bids are often placed 0.01 to 1 TL below the cap, so "at the cap" means within 1 TL/MWh


def load_caps() -> pd.DataFrame:
    caps = pd.read_csv(CAPS_FILE, parse_dates=["effective_date"])
    return caps.sort_values("effective_date").reset_index(drop=True)


def cap_on(dates) -> pd.Series:
    """Maximum PTF in force on each date (TL/MWh); NaN before the first row of the table."""
    caps = load_caps()
    idx = pd.DatetimeIndex(dates)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = idx.normalize()
    pos = caps["effective_date"].searchsorted(idx, side="right") - 1
    values = np.where(pos >= 0, caps["max_tl_mwh"].to_numpy(dtype=float)[np.clip(pos, 0, None)], np.nan)
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def at_cap(price: pd.Series) -> pd.Series:
    """1.0 where the hourly price is within TOLERANCE of the cap, 0.0 where not, NaN where unknown."""
    cap = cap_on(price.index).to_numpy()
    out = np.where(np.isnan(cap) | price.isna().to_numpy(), np.nan, (price.to_numpy() >= cap - TOLERANCE).astype(float))
    return pd.Series(out, index=price.index)
