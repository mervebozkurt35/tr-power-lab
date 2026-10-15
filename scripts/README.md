# Scripts

Python scripts that download and process data.

- `fetch_core.py`: downloads hourly PTF (TRY, EUR, USD), SMF, system direction, real-time consumption and real-time generation by source. Cleans them and writes daily, monthly and recent-hourly files to `data/processed/`, plus a data quality report. Run `python scripts/fetch_core.py --help` for options.
- `price_limits.py`: reads `data/price_caps.csv` (the PTF price cap by period) and flags hours at the cap. Used by `fetch_core.py`.
- `probe_extra.py`: one-off probe. Downloads a few days from candidate EPİAŞ calls (congestion, wind forecast, reservoirs, interconnection lines, gas prices) and prints their columns. Run it before writing a real fetch for a new series.
- `fetch_extra.py`: downloads the extra EPİAŞ series month by month with a full backfill: gas spot (SGP) and balancing (BGP) prices, balancing instructions (bpm-up, bpm-down), wind generation and forecast, the TEİAŞ load plan, interconnection line outages and YEKDEM installed capacity (licensed and unlicensed). It also saves one reservoir snapshot per run, because EPİAŞ publishes only the latest day. Writes daily and monthly files to `data/processed/` and `quality_report_extra.md`. Run `python scripts/fetch_extra.py --help` for options.
- `probe_history.py`: one-off probe of how far back each call goes, plus congestion cost for full months and the interconnection capacity calls. Run it before writing the fetch for those series.
- `gip_volatility.py`: rebuilds the GİP "perfect trader" volatility measure for a month of hourly contracts.

Scripts read credentials from environment variables (`EPTR_USERNAME`, `EPTR_PASSWORD`). In Colab, keep them in Secrets. In GitHub Actions, keep them in the repository's Settings, under Secrets and variables.
