# Scripts

Python scripts that download and process data.

- `gip_volatility.py`: rebuilds the GİP "perfect trader" volatility measure for a month of hourly contracts.

Scripts read credentials from environment variables (`EPTR_USERNAME`, `EPTR_PASSWORD`). In Colab, keep them in Secrets. In GitHub Actions, keep them in the repository's Settings, under Secrets and variables.
