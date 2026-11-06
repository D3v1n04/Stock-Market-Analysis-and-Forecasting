from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter
import pandas as pd
import psycopg
from dotenv import load_dotenv


project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

output_folder = project_root / "reports" / "figures"
output_folder.mkdir(parents=True, exist_ok=True)

tickers = [
    "AMD", "AMZN", "AVGO", "GOOGL", "META",
    "MSFT", "MU", "NVDA", "ORCL", "TSM",
    "SPY", "XLK", "SMH", "XLY", "XLC",
]
sector_etfs = {"XLK", "SMH", "XLY", "XLC"}

with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ticker,
                cumulative_price_return,
                annualized_volatility
            FROM market.performance_summary
            WHERE ticker = ANY(%s)
            ORDER BY ticker;
            """,
            (tickers,),
        )
        rows = cursor.fetchall()

data = pd.DataFrame(
    rows,
    columns=[
        "ticker",
        "cumulative_price_return",
        "annualized_volatility",
    ],
)

if data.empty:
    raise SystemExit("No summary data was returned.")

if data["ticker"].duplicated().any():
    raise SystemExit("Duplicate ticker summaries found.")

if set(data["ticker"]) != set(tickers):
    raise SystemExit("The summary does not contain all expected tickers.")

numeric_columns = [
    "cumulative_price_return",
    "annualized_volatility",
]

for column in numeric_columns:
    data[column] = pd.to_numeric(data[column], errors="raise")

if data[numeric_columns].isna().any().any():
    raise SystemExit("Missing return or volatility values found.")

if (data["annualized_volatility"] < 0).any():
    raise SystemExit("Negative volatility found.")

plt.style.use("seaborn-v0_8-whitegrid")
figure, axis = plt.subplots(figsize=(12, 8))

# Label offsets keep nearby points easier to distinguish.
offsets = {
    "AMZN": (8, 10),
    "GOOGL": (8, 10),
    "META": (8, -15),
    "MSFT": (8, 10),
    "ORCL": (8, -15),
    "XLC": (-28, -16),
    "XLK": (-28, 10),
    "XLY": (8, -16),
}

for row in data.itertuples(index=False):
    if row.ticker == "SPY":
        color, marker, size = "#111827", "*", 220
    elif row.ticker in sector_etfs:
        color, marker, size = "#D97706", "s", 85
    else:
        color, marker, size = "#2563EB", "o", 85

    axis.scatter(
        row.annualized_volatility,
        row.cumulative_price_return,
        color=color,
        marker=marker,
        s=size,
        edgecolors="white",
        linewidths=0.7,
        zorder=3,
    )

    axis.annotate(
        row.ticker,
        (row.annualized_volatility, row.cumulative_price_return),
        xytext=offsets.get(row.ticker, (8, 6)),
        textcoords="offset points",
        fontsize=10,
    )

axis.xaxis.set_major_formatter(PercentFormatter(xmax=1))
axis.yaxis.set_major_formatter(PercentFormatter(xmax=1))

axis.set_xlabel("Annualized volatility of daily price returns")
axis.set_ylabel("Cumulative price return over the full period")
axis.set_title(
    "Price Return vs. Volatility | 2020-01-02 to 2026-09-30",
    fontsize=16,
    pad=15,
)

axis.margins(x=0.15, y=0.12)
axis.grid(alpha=0.3)

legend_items = [
    Line2D(
        [], [], marker="o", linestyle="None",
        color="#2563EB", label="Stocks", markersize=8,
    ),
    Line2D(
        [], [], marker="s", linestyle="None",
        color="#D97706", label="Sector ETFs", markersize=8,
    ),
    Line2D(
        [], [], marker="*", linestyle="None",
        color="#111827", label="SPY", markersize=12,
    ),
]
axis.legend(handles=legend_items, loc="upper left")

figure.text(
    0.02,
    0.015,
    "Source: Alpaca SIP. Split-adjusted prices; dividends excluded. "
    "Volatility annualized using √252. Historical sample only.",
    fontsize=9,
)

figure.tight_layout(rect=(0, 0.05, 1, 1))

output_path = output_folder / "return_vs_volatility.png"
figure.savefig(output_path, dpi=200, bbox_inches="tight")

print(f"Tickers plotted: {len(data)}")
print(f"Chart saved: {output_path}")

plt.show()
