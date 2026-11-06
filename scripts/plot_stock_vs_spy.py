from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FixedLocator, FuncFormatter
import pandas as pd
import psycopg
from dotenv import load_dotenv


project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

output_folder = project_root / "reports" / "figures"
output_folder.mkdir(parents=True, exist_ok=True)

stocks = [
    "AMD", "AMZN", "AVGO", "GOOGL", "META",
    "MSFT", "MU", "NVDA", "ORCL", "TSM",
]

with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ticker, session_date, price_index
            FROM market.daily_price_performance
            WHERE ticker = ANY(%s)
            ORDER BY session_date, ticker;
            """,
            (stocks + ["SPY"],),
        )
        rows = cursor.fetchall()

data = pd.DataFrame(
    rows,
    columns=["ticker", "session_date", "price_index"],
)

if data.empty:
    raise SystemExit("No performance data was returned.")

data["session_date"] = pd.to_datetime(data["session_date"])
data["price_index"] = pd.to_numeric(
    data["price_index"], errors="raise"
)

indexed = data.pivot(
    index="session_date",
    columns="ticker",
    values="price_index",
).sort_index()

missing_tickers = set(stocks + ["SPY"]) - set(indexed.columns)
if missing_tickers:
    raise SystemExit(f"Missing tickers: {sorted(missing_tickers)}")

if indexed.isna().any().any() or (indexed <= 0).any().any():
    raise SystemExit("Missing or nonpositive index values found.")

plt.style.use("seaborn-v0_8-whitegrid")

figure, axes = plt.subplots(
    5,
    2,
    figsize=(15, 18),
    sharex=True,
    sharey=True,
)

for ticker, axis in zip(stocks, axes.flat):
    axis.plot(
        indexed.index,
        indexed[ticker],
        color="#2563EB",
        linewidth=1.5,
        label="Stock",
    )
    axis.plot(
        indexed.index,
        indexed["SPY"],
        color="#111827",
        linewidth=1.8,
        label="SPY",
    )

    axis.set_yscale("log")
    axis.axhline(
        100, color="#9CA3AF", linestyle="--", linewidth=0.8
    )
    axis.set_title(ticker, fontsize=12, fontweight="bold")
    axis.grid(True, which="major", alpha=0.3)
    axis.grid(False, which="minor")

    axis.yaxis.set_major_locator(
        FixedLocator([50, 100, 200, 500, 1000, 2000, 5000])
    )
    axis.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: f"{value:,.0f}")
    )
    axis.xaxis.set_major_locator(mdates.YearLocator(2))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

# Shared axes apply these limits to every panel.
axes.flat[0].set_ylim(
    indexed.min().min() * 0.85,
    indexed.max().max() * 1.15,
)

start_date = indexed.index.min().date()
end_date = indexed.index.max().date()

figure.suptitle(
    f"Each Stock Compared with SPY | {start_date} to {end_date}",
    fontsize=18,
    y=0.995,
)
figure.supylabel(
    "Price index · starting close = 100 · logarithmic scale",
    fontsize=12,
)

handles, labels = axes.flat[0].get_legend_handles_labels()
figure.legend(
    handles,
    labels,
    loc="upper center",
    bbox_to_anchor=(0.5, 0.975),
    ncol=2,
    frameon=False,
)

figure.text(
    0.02,
    0.012,
    "Source: Alpaca SIP daily bars. Split-adjusted prices; "
    "dividends excluded. All panels use the same axes.",
    fontsize=10,
)

figure.tight_layout(
    rect=(0.035, 0.035, 1, 0.95),
    h_pad=2.0,
    w_pad=1.5,
)

output_path = output_folder / "stock_vs_spy_panels.png"
figure.savefig(output_path, dpi=200, bbox_inches="tight")

print(f"Stock panels: {len(stocks)}")
print(f"Sessions per series: {len(indexed)}")
print(f"Chart saved: {output_path}")

plt.show()
