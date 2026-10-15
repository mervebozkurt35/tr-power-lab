# EPİAŞ Transparency Platform: how the calls behave (observations)

Written for TR Power Lab (trpowerlab.com) by Merve Bozkurt. Observed on 15 October 2026 with a personal
account, through the `eptr2` Python library (version 1.3.9), by downloading each call month by month.

This is **not official documentation**. It records what the services returned, so that the next person does not have to
rediscover it. Where something is a guess it says **assumed**; where it is a question for EPİAŞ it says **to confirm**.
Corrections are welcome (bozkurtmerve35@gmail.com).

## 1. Behaviour that applies to many calls

| Topic | What was observed |
|---|---|
| Date window | A window longer than one year is refused with error SEF1117. Downloads are therefore done month by month. |
| End date | Some calls include the end date, some exclude it. **Congestion cost includes the whole end date**: daily requests `d..d+1` returned the cost of two days, and the daily values added up to about twice the monthly totals (checked on February to August 2026). An earlier test in this project had wrongly concluded the opposite. For the other calls the downloader asks for one day more and keeps only the days it needs. To confirm: which calls follow which rule. |
| Empty answer | A month before a series starts, or a month not yet published, comes back as an empty table, not as an error. |
| Time stamps | ISO format with the Istanbul offset (`+03:00`). Some calls give a plain date, some a date plus a separate hour. |
| Clock changes | Five days between 2012 and 2016 have 23 hours (25 March 2012, 31 March 2013, 31 March 2014, 29 March 2015, 27 March 2016), and five repeated time stamps appear in the hourly series. Likely the daylight saving changes; to confirm. |
| Login service | `giris.epias.com.tr` (login) timed out for several days in October 2026 from a Colab (cloud) machine, then recovered. To confirm: are foreign cloud addresses limited? |
| Latest revisions | Recent days are revised: for example the gas "day-after" price is filled in a day later. |

## 2. Natural gas

| Call | Returns | First data | Notes |
|---|---|---|---|
| `ng-spot-prices` (SGP) | Daily `weightedAverage`, `dayAheadPrice`, `intraDayPrice`, `dayAfterPrice` | 2018-07-26 | Eleven days missing in 2018. Unit **assumed** TL per 1,000 Sm3: trade value divided by matched quantity equals the weighted average price (median gap 0.00%), so price is per quantity unit, but the unit itself is to confirm. |
| `ng-balancing-price` (BGP) | `balancingGasPurchase`, `balancingGasSale`, `additionalBalancingPurchase`, `additionalBalancingSale` | 2018-07 | Purchase price is a constant 3.0% above the spot price until 2022 and 5.0% from 2023 (median by year). It looks like a formula, not a market outcome; to confirm. |
| `ng-system-direction` | Daily `systemDirection`, text "Negatif" or "Pozitif" | 2018-09 | Matches the sign of the system imbalance on about 72% of days (1,215 + 910 of 2,965). Meaning of the label to confirm. |
| `ng-imbalance-system` | Daily `imbalance` | 2018-07 | Unit to confirm. |
| `ng-daily-match-qty` | `total` by contract `GGyyyymmdd` | 2018-09 | Unit to confirm (1,000 Sm3 assumed). |
| `ng-daily-trade-volume` | `tradeValueTotal` by contract | 2018-09 | TL assumed. |
| `ng-physical-realization` | Daily `physicalEntry`, `physicalExit` | 2018-09 | Unit to confirm (Sm3 assumed). |

## 3. Electricity: balancing, load plan, generation

| Call | Returns | First data | Notes |
|---|---|---|---|
| `bpm-up`, `bpm-down` | Hourly balancing instructions, delivered volume and net | 2011-11 | Up delivered plus down delivered equals `net` in every hour (131,083 hours). Down values are negative. Instruction codes 0, 1 and 2 are published; the Balancing and Settlement Regulation (Article 4) defines the instruction label as 0 = balancing, 1 = system-constraint relief, 2 = ancillary services. Whether the published code is this label is to confirm. |
| `load-plan` | Hourly load estimation plan (`lep`) | 2011-11 | Daily median difference from real-time consumption: -0.5%. |
| `wind-forecast` | Wind farm generation, forecast and four band columns `quarter1` to `quarter4` | 2019-03-04 | See section 5. |
| `ren-ul-gen` | Hourly energy by source, YEKDEM unlicensed plants only | Zero before 2017; real data from 2017 | Published with a delay: newest month in October 2026 was August 2026. Unit **assumed** MWh. Sources add up to the total in every hour. Solar is 95 to 100% of the total; night-time solar is 0.1%. |
| `ren-capacity` | Monthly installed capacity by source, licensed (`licencedCapacity`), unlicensed (`unlicencedCapacity`) and `total` | 2016-05 | The period parameter must be a full ISO date. 36 rows have no source name (`renewableEnergyType` empty). Unit **assumed** MW. |

## 4. Grid, congestion, interconnections, reservoirs

| Call | Returns | First data | Notes |
|---|---|---|---|
| `congestion-cost` | One total per province (`cityName`, `congestionCost`) for the whole requested window; parameters `price_type` (SMP, MCP) and `order_type` (up, down, both regulations) | Every month from 2015-01 returned data (earlier months not tried) | Unit **assumed** TL. Province names change over time (İÇEL, İST.AVRUPA, İST.ASYA appear in some months). National total at SMP prices was 0.3 billion TL in 2025 and about 16 billion TL in 2026 (rising from February, highest April to June, back to normal by July; mostly Kırklareli and Sakarya); whether this is a real constraint or a reporting change is to confirm. Monthly totals made before October 2026 include the first day of the following month and are corrected by downloading again. |
| `line-capacities` | `totalCapacity`, `availableCapacity` by hour for directions TRGR, GRTR, TRBG, BGTR (parameter `intl_direction`) | 2019-03 (search started in 2018-06) | No data for 2020-07 and 2023-07 to 2023-09; June 2023 has one day; Greek directions also miss 2023-11. From some date there are 2, 3 or 6 rows per direction and hour; they never disagree. Unit **assumed** MW. |
| `international-line-events` | Outages and restrictions with start and end date and hour | 2016-03-10 | 1,017 events, 176 without an end time. Event type spelling varies ("Bakım", "BAKIM", "PLANLI BAKIM", "İşletme Gereği", "İŞLETME GEREĞİ", "Arıza", "ARIZA"). |
| `dams-active-fullness`, `dams-active-volume`, `dams-daily-level`, `dams-daily-volume`, `dams-water-energy-provision` | Daily figures per dam | **Latest day only**: the calls take no date | 78 dams have daily data, 116 are in `dams-info`. `activeFullnessAmount` times (max volume minus min volume) equals `activeVolume` within 1% for all 77 dams checked, so fullness is a percent of usable storage. History can only be built by saving a snapshot every day. To confirm: is any historical source available? |

## 5. Wind generation and forecast: a break on 13 May 2026

The service description on the platform says: total power production and forecast of the monitored wind farms from the
wind power monitoring and forecast centre, updated every 10 minutes; Q5, Q25, Q75 and Q95 are prediction ranges, built
from minimum and maximum risk scenarios.

| | Until 12 May 2026 | From 13 May 2026 |
|---|---|---|
| Rows per day | 144 (10-minute steps) | 93 (15-minute steps, 00:00 to 23:00) |
| Prediction band columns | Present in about 100% of rows | Upper band (Q95) is zero in all rows (49% of May rows have a band, 0% from June) |
| Wind generation in this call divided by real-time wind generation (`rt-gen`), monthly median | 57% to 75% (May 2025 to April 2026) | 97% to 100% (May to October 2026); on single days from about 0.9 to 1.2 |
| Actual generation inside Q5 to Q95 (nominal 90%) | 83% to 96% by year | not available |
| Actual generation inside Q25 to Q75 (nominal 50%) | 47% to 62% by year | not available |

Q5 is exactly 0 in 13% of the rows that have a band, so a zero lower band is a valid value. Because of the break, data before
and after 13 May should not be joined in one series. Questions to EPİAŞ: did the scope or method of the dataset change on that date,
are the bands no longer published, is 93 rows a day expected, and how is the history kept.

## 6. Open questions in one list

1. May data derived from the platform be republished (charts, daily and monthly summaries, CSV downloads) with attribution?
2. Is daily automated use through the REST services acceptable? Any limits on requests, rates or IP addresses?
3. What changed in `wind-forecast` on 13 May 2026, and why do the bands stop? Why is the ratio to real-time wind generation 0.9 to 1.2 on single days after that date?
4. Is the instruction code in the balancing call the regulation's label (0 balancing, 1 system constraint, 2 ancillary services)?
5. Units: gas prices and quantities, congestion cost, unlicensed generation, capacities.
6. Meaning of `systemDirection` in the gas system, and the 3% / 5% rule in the balancing gas price.
7. Congestion cost: which reference price is used (the SMP and MCP options), does it equal the cost of label-1 instructions, and why did it rise from about 0.3 billion TL in 2025 to about 16 billion TL in 2026 (mostly April to June)? Who finally bears this cost in the settlement?
8. Is there a way to get historical reservoir data?
9. Which calls include the end date and which exclude it?
