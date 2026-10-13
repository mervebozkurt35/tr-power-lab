# Scripts

Python scripts that download and process data.

- `fetch_core.py`: downloads hourly PTF (TRY, EUR, USD), SMF, system direction, real-time consumption and real-time generation by source. Cleans them and writes daily, monthly and recent-hourly files to `data/processed/`, plus a data quality report. Run `python scripts/fetch_core.py --help` for options.
- `gip_volatility.py`: rebuilds the GİP "perfect trader" volatility measure for a month of hourly contracts.

Scripts read credentials from environment variables (`EPTR_USERNAME`, `EPTR_PASSWORD`). In Colab, keep them in Secrets. In GitHub Actions, keep them in the repository's Settings, under Secrets and variables.
