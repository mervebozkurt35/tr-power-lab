"""
GİP "Perfect Trader" volatility report — a reconstruction of Robokami's
monthly GİP Volatilite Raporu.

Method (from the report's own assumptions):
  * Data: EPİAŞ Şeffaflık GİP İşlem Akışı (eptr2 call "idm-log").
  * Only hourly contracts (PH...).
  * A "Perfect Trader" (MT) starts and ends every contract flat, can take
    either side of every trade (or skip it, or take part of it), does not
    move the market, and pays no costs.

Under those assumptions trade ORDER does not matter (no position limit in
between), so the MT's best play is: sell the most expensive half of the
contract's traded volume and buy the cheapest half. That optimum equals

    profit = Σ q_i · |p_i − m|        (m = volume-weighted median price)

i.e. a volume-weighted L1 dispersion of trade prices around the median.
That is why the report calls it "volatility": it is price dispersion
within a contract, scaled by how much volume traded.

Usage:
    pip install "eptr2[allextras]" plotly kaleido
    # put EPTR_USERNAME / EPTR_PASSWORD (Şeffaflık account) in a .env file
    python gip_volatility.py --month 2026-09 --ptf 2821.8
    python gip_volatility.py --csv idm_log_2026-09.csv     # reuse saved data
"""

import argparse
import sys

import pandas as pd

LOT_MWH = 0.1  # one GİP lot = 0.1 MWh
TR_DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


# ----------------------------------------------------------------------------
# Core: the Perfect Trader optimum for one contract
# ----------------------------------------------------------------------------
def perfect_trader_profit(prices, lots):
    """Max profit (TL) for one contract.

    prices: TL/MWh per trade; lots: traded lots per trade.
    Returns TL (lots converted to MWh with LOT_MWH).
    """
    df = pd.DataFrame({"p": prices, "q": lots}).sort_values("p")
    half = df["q"].sum() / 2.0
    cum = df["q"].cumsum()
    # volume-weighted median: first price where cumulative volume reaches half
    median = df.loc[cum >= half, "p"].iloc[0]
    return float((df["q"] * (df["p"] - median).abs()).sum() * LOT_MWH)


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def fetch_month(month):
    """Download every GİP trade for the PH contracts delivered in `month`."""
    from eptr2 import EPTR2
    from eptr2.composite.idm_log import idm_log_period

    eptr = EPTR2(use_dotenv=True, recycle_tgt=True)
    return idm_log_period(f"{month}-01", eptr=eptr, verbose=True)


def _col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    sys.exit(f"Column not found, looked for {names}. Columns: {list(df.columns)}")


def contract_table(log):
    """One row per PH contract: volume, VWAP, Perfect-Trader profit."""
    c_name = _col(log, "contractName", "contract_name", "kontrat")
    c_price = _col(log, "price", "fiyat")
    c_qty = _col(log, "quantity", "miktar", "qty")

    ph = log[log[c_name].astype(str).str.startswith("PH")].copy()

    rows = []
    for name, g in ph.groupby(c_name):
        lots = g[c_qty].sum()
        rows.append(
            {
                "contract": name,
                "day": name[:8],  # PHyyMMdd
                "hour": name[8:10],
                "lots": lots,
                "mwh": lots * LOT_MWH,
                "vwap": (g[c_price] * g[c_qty]).sum() / lots,
                "profit_tl": perfect_trader_profit(g[c_price], g[c_qty]),
            }
        )
    out = pd.DataFrame(rows).sort_values("contract").reset_index(drop=True)
    out["profit_per_mwh"] = out["profit_tl"] / out["mwh"]
    return out


def summary(ct, ptf=None):
    total = ct["profit_tl"].sum()
    lots = ct["lots"].sum()
    mwh = ct["mwh"].sum()
    s = {
        "Toplam Net Kar (TL)": total,
        "Toplam Lot": lots,
        "Toplam MWh": mwh,
        "MWh Başına Ortalama Kar (TL/MWh)": total / mwh,
    }
    if ptf:
        s["Aylık Ağırlıklı Ort. PTF (TL/MWh)"] = ptf
        s["PTF'ye Göre Marj (%)"] = 100 * (total / mwh) / ptf
    return s


# ----------------------------------------------------------------------------
# Chart: one bar per delivery day, stacked by hour (like the report)
# ----------------------------------------------------------------------------
def plot(ct, path):
    import plotly.express as px

    ct = ct.copy()
    dt = pd.to_datetime(ct["day"].str[2:], format="%y%m%d")
    ct["label"] = [f"{TR_DAYS[d.weekday()]} - {c}" for d, c in zip(dt, ct["day"])]
    order = sorted(ct["label"].unique(), key=lambda s: s.split(" - ")[1])

    fig = px.bar(
        ct,
        x="profit_tl",
        y="label",
        color="hour",
        orientation="h",
        category_orders={"label": order[::-1], "hour": sorted(ct["hour"].unique())},
        labels={"profit_tl": "Toplam Volatilite", "label": "Kontrat Günü", "hour": "Saat"},
        title="Kontrat Volatiliteleri",
        height=max(500, 28 * len(order)),
    )
    fig.update_layout(plot_bgcolor="white", bargap=0.15)
    fig.update_xaxes(gridcolor="#bbb")
    if path.endswith(".html"):
        fig.write_html(path)
    else:
        fig.write_image(path, scale=2)
    return fig


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM, downloads from EPİAŞ via eptr2")
    ap.add_argument("--csv", help="use an already-saved idm-log CSV instead")
    ap.add_argument("--ptf", type=float, help="monthly weighted average PTF, TL/MWh")
    args = ap.parse_args()

    if args.csv:
        log = pd.read_csv(args.csv)
        tag = args.csv.rsplit(".", 1)[0]
    elif args.month:
        log = fetch_month(args.month)
        tag = f"idm_log_{args.month}"
        log.to_csv(f"{tag}.csv", index=False)
    else:
        ap.error("give --month or --csv")

    ct = contract_table(log)
    ct.to_csv(f"{tag}_contracts.csv", index=False)
    for k, v in summary(ct, args.ptf).items():
        print(f"{k:38s} {v:,.1f}")
    # HTML needs nothing extra; for PNG use plot(ct, "x.png") with kaleido + Chrome
    plot(ct, f"{tag}_volatility.html")
    print(f"Saved {tag}_contracts.csv and {tag}_volatility.html")


if __name__ == "__main__":
    main()
