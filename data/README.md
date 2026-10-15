# Data

The site is built on three layers, so history is collected once and every later run only adds new days.

| Layer | Where | What it holds | In the public repo |
|---|---|---|---|
| Raw | `data/raw/` (kept in Google Drive) | Hourly data exactly as EPİAŞ returns it, one file per series and month | No |
| Processed | `data/processed/` | Cleaned daily and monthly series that charts and reports read | Daily and monthly only |
| Events | `data/events.csv` | Dated structural changes that charts annotate and reports refer to | Yes |

## How updates work

`scripts/fetch_core.py` keeps the full history on disk. Each run skips months it already has, re-downloads only the most recent months (EPİAŞ revises them), and rebuilds the processed files. Adding a new series means adding it to the script once; the first run backfills its whole history and later runs keep it current.

## Events file

One row per event. Charts draw a marker for every row with `status = verified` whose `series` matches the chart.

| Column | Meaning |
|---|---|
| `date` | Day the change took effect (YYYY-MM-DD) |
| `end_date` | Optional, for periods such as a drought or a lockdown |
| `category` | `regulation`, `market_design`, `macro`, `weather`, `supply`, `demand`, `geopolitics` or `data` |
| `title` | Short label shown on the chart |
| `description` | One or two sentences, with what the data shows |
| `series` | Which series it relates to, separated by `;` (for example `ptf;smf`) |
| `source` | Link to the decision, law or news item; `observed in data` until confirmed |
| `status` | `draft` until the date and source are confirmed, then `verified` |


## price_caps.csv

PTF price cap by period (decision date, first delivery day, limit, status, source). `verified` means a dated press report agrees with the data; `draft` means the change is seen in the data but the decision is not confirmed. The same changes are also listed as `regulation` rows in `events.csv`, which are generated from this file: edit `price_caps.csv` first, then update `events.csv`.


## Extra EPİAŞ series (`scripts/fetch_extra.py`)

Written to `data/processed/`:

| File | Content |
|---|---|
| `gas_daily.csv`, `gas_monthly.csv` | Spot gas (SGP) and gas balancing (BGP) prices as published (assumed TL per 1,000 Sm3), TL/MWh using BOTAŞ's 9,155 kcal/Sm3, and EUR and USD versions using the implied exchange rate |
| `balancing_daily.csv`, `balancing_monthly.csv` | Upward and downward balancing instructions by instruction code, MWh |
| `wind_daily.csv` | Monitored wind farms: generation, forecast, forecast error, share of real-time wind |
| `load_plan_daily.csv` | TEİAŞ load plan against real-time consumption |
| `line_events.csv` | Interconnection line outages and maintenance |
| `ren_capacity_monthly.csv` | YEKDEM installed capacity by source, licensed and unlicensed |
| `reservoirs_daily.csv`, `reservoirs_info.csv` | Reservoir snapshots, one row per dam and day |
| `quality_report_extra.md` | Ranges, gaps and checks from the last run |

**Reservoir history cannot be backfilled.** EPİAŞ returns only the latest day, so `reservoirs_daily.csv` is the only copy of the history and starts on the first day the script ran. Commit it, and run the script every day (until the automation does) so no day is lost.
