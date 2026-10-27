# Data

The site is built on three layers, so history is collected once and every later run only adds new days.

| Layer | Where | What it holds | In the public repo |
|---|---|---|---|
| Raw | `data/raw/` (kept in Google Drive) | Hourly data exactly as EPİAŞ returns it, one file per series and month | No |
| Processed | `data/processed/` | Cleaned daily and monthly series that charts and reports read | Daily and monthly only |
| Events | `data/events.csv` | Dated structural changes that charts annotate and reports refer to | Yes |

## Daily update

`.github/workflows/update-data.yml` runs every morning (06:37 Istanbul time). It starts `scripts/update_data.py`, which downloads recent months from EPİAŞ, rebuilds them and replaces the newest rows in `data/processed/`. Older rows are never rewritten. How far back it rewrites depends on the day, because recent values can be completed or revised after first publication: every day only the new day is added, on Mondays the last 7 days are rewritten, and on the 1st of each month the last 2 months. A manual run can also choose `deep` (6 months). Downloads are always whole months, because the monthly files are built from a complete month. Series that publish late (unlicensed generation, outage end dates) have longer look-backs. `data/processed/revision_log.csv` records, for every run, how many days were revised and how old they were, so the window can be shortened or kept based on what actually changes. On Mondays and on the 1st the e-mail also has a section "Changes in the re-downloaded period": which stored values changed, in which files and columns, and by how much (the full list of old and new values is the file `changes.csv` in the build artifact of that run). A month that is still in progress is not counted as a revision. If the data is behind by more than the window (for example after a pause), the window widens by itself and fills the gap. The new files are committed to `main`, the site is rebuilt and published in the same run, and an overview of the latest day (prices, demand, generation, update status) is sent by e-mail.

### E-mail after each run

`scripts/daily_digest.py` writes the overview and the `notify` job sends it. It needs three repository secrets (Settings > Secrets and variables > Actions): `MAIL_USERNAME` (sender address, Gmail by default), `MAIL_APP_PASSWORD` (a Google app password, not the normal password) and optionally `MAIL_TO`. Without them no mail is sent and the run is not marked as failed. A manual run with "write" unticked sends a mail marked TRIAL.

- `data/processed/update_status.json` records the newest day in each file, the time of the last check, and any warnings or errors. The data pages show "Data through …" from it.
- A file is replaced only if its checks pass (columns, row count, plausible consumption and prices). If a series fails, its old rows stay, the rest is still published, and the run is marked failed so GitHub sends an email.
- A value that was in a file and comes back empty is treated as a failed download and the old value is kept.
- The reservoir snapshot is taken first, because EPİAŞ returns only the latest day.
- The raw hourly files are not needed for this. `fetch_core.py` and `fetch_extra.py` remain for a full rebuild or a new series (run them in Colab, then commit the processed files).

## How a full rebuild works

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
| `line_events.csv`, `line_capacity_daily.csv` | Interconnection line outages and maintenance; line capacities by direction |
| `ul_gen_daily.csv`, `ul_gen_monthly.csv` | YEKDEM unlicensed generation by source (only unlicensed plants inside YEKDEM; source labels look unreliable) |
| `congestion_monthly.csv`, `congestion_province_monthly.csv` | Congestion (redispatch) cost by province at SMP and PTF prices, up and down regulation |
| `ren_capacity_monthly.csv` | YEKDEM installed capacity by source, licensed and unlicensed |
| `reservoirs_daily.csv`, `reservoirs_info.csv`, `reservoirs_national_daily.csv`, `reservoirs_basin_daily.csv` | Reservoir snapshots, one row per dam and day, dam details with min and max volume, and national and basin fullness |
| `entsoe_flows_turkey.csv` | Not written by the daily update: a one-off download from the ENTSO-E Transparency Platform (Physical Energy & Power Flows), merged by hand. Monthly energy (GWh) and two snapshot power flows per month (MW, third Wednesday at 03:00 and 11:00) between Türkiye and Bulgaria, Greece, Georgia and, to 2019 only, Armenia, Azerbaijan, Iraq, Iran and Syria. Columns: year, month, border, measure, tr_export, tr_import (Türkiye's view), source of each value, tr_net_import. Türkiye's own report is used where it exists, otherwise the neighbour's report with the direction flipped. Data to June 2026. |
| `quality_report_extra.md` | Ranges, gaps and checks from the last run |

**Reservoir history cannot be backfilled.** EPİAŞ returns only the latest day, so `reservoirs_daily.csv` is the only copy of the history and starts on the first day the script ran. Commit it, and the daily workflow (`update-data.yml`) runs the snapshot first, so no day is lost.

## Regulation section (`data/regulation/`)

Hand-built from public pages, not from EPİAŞ. `scripts/regulation_view.py` reads these files and the pages in `regulation/` render them.

| File | Content |
|---|---|
| `milestones.csv` | The cards of the timeline: `id`, `date` (sort key), `shown` (date as displayed), `tag` (Liberalisation, Power market, Generation, Grid and system operation or Market transition), `title`, `summary` (1 to 3 sentences), `tags` (legal tags), `s1_label`/`s1_url`/`s2_label`/`s2_url` (up to two sources and what kind they are), `instruments` (ids from `events.csv`) |
| `events.csv` | One row per instrument or event: `id`, `date`, `date_type`, `title`, `label` (short name), `name_tr` (Turkish name where read on an official list), `instrument` (number and gazette), `kind`, `area`, `institutions` (codes joined by `;`), `parent` (the `id` of the instrument it rests on), `relation`, `effect`, `source_url`, `source_note`, `status` |
| `institutions.csv` | `code`, `name`, `role`, `legal_basis`, `status` |
| `coverage.csv` | Every instrument on EPDK's electricity index, EPİAŞ's legislation page and the EPDK procedure pages against the timeline, with a priority (`high`, `medium`, `low`, `history`, `out of scope`) |
| `research_log.csv` | Each source opened for an entry, and failed or disputed attempts |

`verified` means the title, number and date were read on a page that reproduces the official text or on an official page; `draft` means handbook, news or inference. A card's status is the status of its first instrument, and sentences that come from the handbook or the press say so. Add a milestone by adding a row with instrument ids that exist in `events.csv`.
