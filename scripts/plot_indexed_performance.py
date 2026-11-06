from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg
from dotenv import load_dotenv


project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

output_folder = project_root / "reports" / "figures"
output_folder.mkdir(parents=True, exist_ok=True)

query = """
SELECT ticker, session_date, price_index
FROM market.daily_price_performance
ORDER BY session_date, ticker;
"""

with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.execute(query)
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

# One column per ticker, with trading dates on the rows.
indexed = data.pivot(
    index="session_date",
    columns="ticker",
    values="price_index",
).sort_index()

if indexed.isna().any().any():
    raise SystemExit("Missing values found in the indexed series.")

if (indexed <= 0).any().any():
    raise SystemExit("A logarithmic chart requires positive values.")

plt.style.use("seaborn-v0_8-whitegrid")
figure, axes = plt.subplots(figsize=(14, 8))

colors = plt.get_cmap("tab20")

for position, ticker in enumerate(indexed.columns):
    is_benchmark = ticker == "SPY"

    axes.plot(
        indexed.index,
        indexed[ticker],
        label=ticker,
        color="black" if is_benchmark else colors(position),
        linewidth=2.8 if is_benchmark else 1.3,
        alpha=1.0 if is_benchmark else 0.85,
    )

axes.set_yscale("log")
axes.axhline(100, color="gray", linestyle="--", linewidth=1)

start_date = indexed.index.min().date()
end_date = indexed.index.max().date()

axes.set_title(
    f"Indexed Price Performance | {start_date} to {end_date}",
    fontsize=16,
    pad=15,
)
axes.set_xlabel("Trading date")
axes.set_ylabel("Price index · starting close = 100 · logarithmic scale")

axes.legend(
    title="Ticker",
    bbox_to_anchor=(1.02, 1),
    loc="upper left",
)

figure.text(
    0.01,
    0.015,
    "Source: Alpaca SIP daily bars. Split-adjusted prices; "
    "dividends excluded. SPY shown in black.",
    fontsize=9,
)

figure.tight_layout(rect=(0, 0.05, 1, 1))

output_path = output_folder / "indexed_price_performance.png"
figure.savefig(output_path, dpi=200, bbox_inches="tight")

print(f"Tickers plotted: {len(indexed.columns)}")
print(f"Sessions per ticker: {len(indexed)}")
print(f"Date range: {start_date} to {end_date}")
print(f"Chart saved: {output_path}")

plt.show()
