from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import PercentFormatter
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
            SELECT ticker, session_date, drawdown
            FROM market.daily_price_drawdowns
            WHERE ticker = ANY(%s)
            ORDER BY session_date, ticker;
            """,
            (stocks + ["SPY"],),
        )
        rows = cursor.fetchall()

data = pd.DataFrame(
    rows,
    columns=["ticker", "session_date", "drawdown"],
)

if data.empty:
    raise SystemExit("No drawdown data was returned.")

data["session_date"] = pd.to_datetime(data["session_date"])
data["drawdown"] = pd.to_numeric(
    data["drawdown"], errors="raise"
)

drawdowns = data.pivot(
    index="session_date",
    columns="ticker",
    values="drawdown",
).sort_index()

missing_tickers = set(stocks + ["SPY"]) - set(drawdowns.columns)
if missing_tickers:
    raise SystemExit(f"Missing tickers: {sorted(missing_tickers)}")

if drawdowns.isna().any().any():
    raise SystemExit("Missing drawdown values found.")

if ((drawdowns > 0) | (drawdowns < -1)).any().any():
    raise SystemExit("Drawdown values outside [-1, 0] found.")

plt.style.use("seaborn-v0_8-whitegrid")

figure, axes = plt.subplots(
    5,
    2,
    figsize=(15, 18),
    sharex=True,
    sharey=True,
)

for ticker, axis in zip(stocks, axes.flat):
    axis.fill_between(
        drawdowns.index,
        drawdowns[ticker].to_numpy(dtype=float),
        0,
        color="#2563EB",
        alpha=0.15,
    )
    axis.plot(
        drawdowns.index,
        drawdowns[ticker],
        color="#2563EB",
        linewidth=1.3,
        label="Stock",
    )
    axis.plot(
        drawdowns.index,
        drawdowns["SPY"],
        color="#111827",
        linewidth=1.5,
        label="SPY",
    )

    worst = drawdowns[ticker].min()
    axis.set_title(
        f"{ticker} | Maximum drawdown: {worst:.1%}",
        fontsize=12,
        fontweight="bold",
    )

    axis.axhline(0, color="#9CA3AF", linewidth=0.8)
    axis.set_ylim(-1, 0.02)
    axis.set_yticks([-1, -0.75, -0.5, -0.25, 0])
    axis.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    axis.xaxis.set_major_locator(mdates.YearLocator(2))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axis.grid(True, alpha=0.3)

start_date = drawdowns.index.min().date()
end_date = drawdowns.index.max().date()

figure.suptitle(
    f"Drawdowns Compared with SPY | {start_date} to {end_date}",
    fontsize=18,
    y=0.995,
)
figure.supylabel(
    "Decline from the running peak closing price",
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
    "dividends excluded. Peaks measured from the dataset start.",
    fontsize=10,
)

figure.tight_layout(
    rect=(0.035, 0.035, 1, 0.95),
    h_pad=2.0,
    w_pad=1.5,
)

output_path = output_folder / "stock_vs_spy_drawdowns.png"
figure.savefig(output_path, dpi=200, bbox_inches="tight")

print(f"Stock panels: {len(stocks)}")
print(f"Sessions per series: {len(drawdowns)}")
print(f"SPY maximum drawdown: {drawdowns['SPY'].min():.2%}")
print(f"Chart saved: {output_path}")

plt.show()
