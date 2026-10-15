# Quality report: extra EPİAŞ series

Written by `scripts/fetch_extra.py`. Latest run: 2026-10-15 15:43.

## Gas prices (SGP and BGP)

- Range: 2018-07-26 to 2026-10-14, 2992 days.
- Days without a row: 11 (2018-07-27..2018-07-30, 2018-08-20..2018-08-26).
- Unit assumed: TL per 1,000 Sm3 as published; TL/MWh uses 9155 kcal/Sm3 (1,000 Sm3 = 10.65 MWh). Both to be confirmed.
- `sgp_wavg`: 2965 values, min 1,205, median 9,897, max 26,297; zero or negative: 0.
- `bgp_buy`: 2966 values, min 1,241, median 10,390, max 27,086; zero or negative: 0.
- `bgp_sell`: 2966 values, min 1,169, median 9,453, max 25,508; zero or negative: 0.
- Day-on-day moves above 50% in the spot price: 3 (first: 2022-01-04, 2025-02-14, 2025-02-15).
- Isolated one-day spikes or dips in the spot price (flagged `sgp_outlier = 1`, left in the data): 4: 2022-01-03 (6,652), 2022-11-22 (13,997), 2024-09-30 (8,851), 2025-02-14 (1,246).
- Days with a day-ahead price but no weighted average yet (published a day later): 2026-10-14.
- Balancing purchase price above the spot price, median % by year: 2018: 3.0, 2019: 3.0, 2020: 3.0, 2021: 3.0, 2022: 3.0, 2023: 5.0, 2024: 5.1, 2025: 5.1, 2026: 5.0. A constant percentage means the balancing price follows a formula around the reference price rather than a market outcome.
- Days where the balancing purchase price is below the sale price (unexpected): 0.
- Spot trade value divided by matched quantity versus the weighted average price: median gap 0.00%, above 1% on 1 of 2965 days. Agreement means the price is per quantity unit; the unit itself (assumed 1,000 Sm3) is still unconfirmed.
- Spot matched quantity as a share of physical gas entry (if the quantity is in 1,000 Sm3, entry in Sm3): median 1.32%, max 24.34%.
- System direction (as published) against the sign of the system imbalance, number of days:

| gas_system_direction   |   negative |   positive |   zero |
|:-----------------------|-----------:|-----------:|-------:|
| Negatif                |       1215 |        573 |      0 |
| Pozitif                |        266 |        910 |      1 |
| missing                |         15 |         12 |      0 |

  Do not label either direction 'short' or 'long' on the site until the match is understood.

## Balancing instructions (bpm-up, bpm-down)

- Range: 2011-11-01 to 2026-10-14, 5462 days, 131,083 hours.
- Days with fewer than 24 hours: 5 (2012-03-25, 2013-03-31, 2014-03-31, 2015-03-29, 2016-03-27).
- Check: up delivered + down delivered vs `net` differ by more than 1 MWh in 0 of 131083 hours.
- Down-delivered values are negative in 103597 hours and positive in 0 (sign convention check).
- Instruction code 0, 1 and 2 are published as is; their exact meaning is not documented here yet (code 1 is expected to be grid-constraint instructions). Do not describe them on the site until confirmed.

## Wind generation and forecast (wind-forecast)

- Range: 2019-03-04 to 2026-10-14, 2781 days, 392,559 rows.
- Most common time step by year (minutes): 2019: 10, 2020: 10, 2021: 10, 2022: 10, 2023: 10, 2024: 10, 2025: 10, 2026: 15.
- Rows per day: {144: 2626, 93: 155} (rows: number of days).
- Days where generation or forecast covers less than 90% of the day: 44 (2019-05-25, 2019-06-09, 2019-07-25..2019-07-27, 2019-09-14, 2019-09-16, 2019-09-27, 2019-10-14, 2019-10-30..2019-10-31 (+27 more ranges)). Energy, forecast error and the share of real-time wind are only meaningful on the other days.
- Missing forecast values: 173; missing generation values: 5195.
- Prediction bands (`quarter1`..`quarter4` taken as Q5, Q25, Q75, Q95 per EPİAŞ's description; a band counts as published when Q95 is above 0, Q5 = 0 is allowed). Rows with valid bands by year: 2019: 95%, 2020: 100%, 2021: 100%, 2022: 100%, 2023: 100%, 2024: 100%, 2025: 100%, 2026: 57%. Last months: 2026-03: 100%, 2026-04: 100%, 2026-05: 49%, 2026-06: 0%, 2026-07: 0%, 2026-08: 0%, 2026-09: 0%, 2026-10: 0%. Rows where the bands are present but not in ascending order: 0 of 375721. Rows with a valid band where Q5 is exactly 0: 49473.
- Share of actual generation inside the bands (a calibrated forecast would show 90% and 50%): 2019: 85% / 51%; 2020: 93% / 57%; 2021: 94% / 61%; 2022: 90% / 55%; 2023: 86% / 47%; 2024: 83% / 48%; 2025: 96% / 59%; 2026: 96% / 62%.
- Same ratio by month (last 18 months): 2025-05: 75%, 2025-06: 73%, 2025-07: 65%, 2025-08: 67%, 2025-09: 65%, 2025-10: 68%, 2025-11: 61%, 2025-12: 57%, 2026-01: 61%, 2026-02: 61%, 2026-03: 61%, 2026-04: 67%, 2026-05: 97%, 2026-06: 98%, 2026-07: 99%, 2026-08: 99%, 2026-09: 99%, 2026-10: 100%. A step in this ratio marks a change in which plants the call covers.
- Wind generation in this call divided by real-time wind generation (rt-gen), complete days only: median 76%, min 7%, max 103%; by year 2019: 72%, 2020: 78%, 2021: 81%, 2022: 81%, 2023: 75%, 2024: 73%, 2025: 67%, 2026: 96%. Below 100%: the call may cover only part of the wind fleet, so use it for forecast error, not totals. A sudden change in this ratio points to a change in the dataset, not in the weather.
- Months with missing wind values: 2025-07: gen 31, fc 0; 2025-08: gen 31, fc 0; 2025-09: gen 30, fc 0; 2025-10: gen 203, fc 157; 2025-11: gen 72, fc 15; 2025-12: gen 55, fc 0; 2026-01: gen 27, fc 0; 2026-02: gen 28, fc 0; 2026-03: gen 31, fc 0; 2026-04: gen 30, fc 0; 2026-05: gen 236, fc 0; 2026-08: gen 67, fc 0.

## Load plan (load-plan)

- Range: 2011-11-01 to 2026-10-14, 5461 days.
- Days with fewer than 24 hours: 5 (2012-03-25, 2013-03-31, 2014-03-31, 2015-03-29, 2016-03-27).
- Plan versus real-time consumption, daily: median -0.5%, 5th to 95th percentile -5.7% to +4.3%. Real-time consumption includes unmetered embedded generation from 30 Dec 2020, so compare periods on the same side of that date.

## YEKDEM unlicensed generation (ren-ul-gen)

- Range: 2011-11-01 to 2026-08-31, 5418 days (the newest months are published with a delay). Unit assumed MWh per hour.
- Days with fewer than 24 hours: 5 (2012-03-25, 2013-03-31, 2014-03-31, 2015-03-29, 2016-03-27).
- Sources add up to the published total (within 1 MWh) in 129307 of 129307 hours.
- Share of 'solar' energy booked between 21:00 and 03:59: 0.1%. Real solar output is zero at night, so a large share means the source labels are not reliable.
- Shares by year (this series covers only unlicensed plants inside YEKDEM, not all unlicensed plants):

| Year | Total (GWh) | Solar share | 'Other' share |
|---|---:|---:|---:|
| 2011 | 0 | - | - |
| 2012 | 0 | - | - |
| 2013 | 0 | - | - |
| 2014 | 0 | - | - |
| 2015 | 0 | - | - |
| 2016 | 0 | - | - |
| 2017 | 2,148 | 100% | 0% |
| 2018 | 8,077 | 96% | 0% |
| 2019 | 9,831 | 95% | 0% |
| 2020 | 11,230 | 96% | 0% |
| 2021 | 12,149 | 97% | 0% |
| 2022 | 12,734 | 97% | 0% |
| 2023 | 15,070 | 97% | 2% |
| 2024 | 20,959 | 98% | 1% |
| 2025 | 30,143 | 98% | 1% |
| 2026 | 24,098 | 97% | 1% |

## Congestion cost by province (congestion-cost)

- Range: 2015-01 to 2026-10, 142 months; 140 months with a non-zero national total. Unit assumed TL.
- National total at SMP prices (up + down regulation), million TL per year: 2015: 831.6, 2016: 1,158.2, 2017: 419.7, 2018: 83.3, 2019: 648.4, 2020: 108.0, 2021: 248.3, 2022: 1,125.9, 2023: 1,157.8, 2024: 828.5, 2025: 314.5, 2026: 16,542.6.
- Largest provinces over the whole history (SMP, million TL): KIRKLARELİ 6,900.5, SAKARYA 5,021.8, İSTANBUL-AVRUPA 2,758.9, ÇANAKKALE 1,575.4, BALIKESİR 1,147.1, ARTVİN 1,059.3.
- Largest national monthly totals (SMP, million TL): 2026-05: 6,122, 2026-06: 4,488, 2026-04: 4,090, 2026-03: 1,085, 2019-05: 377, 2022-04: 302. A few months far above the rest point to events or to a change in how the figure is reported; check before charting.
- Largest provinces in 2026 so far (SMP, million TL): KIRKLARELİ 6,176, SAKARYA 4,954, ÇANAKKALE 1,296, İSTANBUL-AVRUPA 1,098, BALIKESİR 956.
- Negative values: 2. Rows per month: 328 (median).

## Interconnection line capacities (line-capacities)

- Range: 2019-03-01 to 2026-10-09. Unit assumed MW.
- Rows per direction and hour, as {rows: number of direction-hours}: {1: 141072, 2: 112, 3: 101448, 6: 12}. Hours where the repeated rows disagree: 0.
- BGTR: 2019-03 to 2026-10, months with no data: 4 (2020-07, 2023-07, 2023-08, 2023-09). Total capacity values seen: [100.0, 150.0, 166.0, 172.0, 174.0, 176.0].
- GRTR: 2019-03 to 2026-10, months with no data: 5 (2020-07, 2023-07, 2023-08, 2023-09, 2023-11). Total capacity values seen: [0.0, 23.0, 50.0, 63.0, 65.0, 69.0].
- TRBG: 2019-03 to 2026-10, months with no data: 4 (2020-07, 2023-07, 2023-08, 2023-09). Total capacity values seen: [0.0, 100.0, 108.0, 110.0, 111.0, 114.0].
- TRGR: 2019-03 to 2026-10, months with no data: 5 (2020-07, 2023-07, 2023-08, 2023-09, 2023-11). Total capacity values seen: [0.0, 11.0, 16.0, 35.0, 48.0, 50.0].

## Interconnection line events

- 1017 events from 2016-03-10 to 2026-10-14; 176 without an end time.
- Event types as published: {'Bakım': 308, 'İşletme Gereği': 265, 'Arıza': 238, 'İŞLETME GEREĞİ': 167, 'PLANLI BAKIM': 30, 'BAKIM': 7, 'ARIZA': 2}; grouped (`type_clean`): {'operational': 432, 'maintenance': 345, 'fault': 240}.

## YEKDEM installed capacity (ren-capacity)

- Range: 2016-05 to 2026-10, 126 months.
- Source categories not renamed: ['Biyogaz', 'Diğer', 'LFG-Çöp Gazı']. Unit assumed MW.

- Latest month (2026-10): solar licensed 1,469 MW, unlicensed 23,859 MW.

## Reservoirs (snapshots)

- 1 daily snapshot(s) saved, first 2026-10-15, latest 2026-10-15: 78 dams, 78 with usable-volume information.
- Check: active fullness x (max - min volume) matches active volume within 1% for 100% of 77 dam-days. If this holds, fullness is the percent of usable storage.
- National active volume 12,388 of 23,321 usable (same unit as EPİAŞ's volumes, assumed million m3): 53.1% on 2026-10-15.

## Notes from the run

- gas: 2 gas days have no implied exchange rate (PTF in EUR missing or zero); EUR and USD prices are empty on those days.
- bpm_up: 5 duplicate timestamps removed.
- bpm_down: 5 duplicate timestamps removed.
- load_plan: 5 duplicate timestamps removed.
- ul_gen: 5 duplicate timestamps removed.
- ren_capacity: 36 rows have no source name and were left out.
