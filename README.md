# TR Power Lab

Data and analysis on Türkiye's electricity market: prices, generation, monthly reports, tools and lessons, built on public data with open code.

Website: https://mervebozkurt35.github.io/tr-power-lab/ (later trpowerlab.com)

## What is in this repository

| Folder | Contents |
|---|---|
| `markets/`, `reports/`, `blog/`, `tools/`, `learn/` | Website pages, written in Quarto (`.qmd`) |
| `assets/` | Site theme: colours and fonts |
| `scripts/` | Python scripts that download and process data |
| `notebooks/` | Exploratory Colab notebooks |
| `data/processed/` | Small aggregated files the site reads |
| `data/raw/` | Local only, never committed |
| `.github/workflows/` | Builds and publishes the site automatically |

## How the site is built

Every change pushed to the `main` branch starts a GitHub Actions run. It renders the Quarto site and publishes it to GitHub Pages. No local installation is needed.

## Data sources

- [EPİAŞ Şeffaflık Platformu](https://seffaflik.epias.com.tr), accessed with [eptr2](https://github.com/Tideseed/eptr2)
- EPDK licence registers
- ENTSO-E Transparency Platform (planned)

TR Power Lab is independent and not affiliated with EPİAŞ, TEİAŞ or EPDK.

## Licence

Code is released under the MIT licence.
