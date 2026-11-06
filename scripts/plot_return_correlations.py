from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from dotenv import load_dotenv


project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

output_folder = project_root / "reports" / "figures"
output_folder.mkdir(parents=True, exist_ok=True)

# Group related stocks and benchmarks together.
tickers = [
    "AMD", "NVDA", "MU", "AVGO", "TSM", "SMH",
    "MSFT", "ORCL", "XLK",
    "GOOGL", "META", "XLC",
    "AMZN", "XLY", "SPY",
]

with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ticker,
                session_date,
                previous_session_date,
                daily_price_return
            FROM market.daily_price_returns
            WHERE ticker = ANY(%s)
              AND daily_price_return IS NOT NULL
            ORDER BY session_date, ticker;
            """,
            (tickers,),
        )
        rows = cursor.fetchall()

data = pd.DataFrame(
    rows,
    columns=[
        "ticker",
        "session_date",
        "previous_session_date",
        "daily_price_return",
    ],
)

if data.empty:
    raise SystemExit("No daily returns were returned.")

if set(data["ticker"]) != set(tickers):
    raise SystemExit("Missing expected tickers.")

if data.duplicated(["session_date", "ticker"]).any():
    raise SystemExit("Duplicate ticker/date returns found.")

data["session_date"] = pd.to_datetime(data["session_date"])
data["previous_session_date"] = pd.to_datetime(
    data["previous_session_date"]
)
data["daily_price_return"] = pd.to_numeric(
    data["daily_price_return"], errors="raise"
)

if data.isna().any().any():
    raise SystemExit("Missing dates or return values found.")

# All tickers on a date must use the same previous session.
previous_dates = data.groupby("session_date")[
    "previous_session_date"
].nunique()

if (previous_dates != 1).any():
    raise SystemExit("Return intervals differ across tickers.")

returns = data.pivot(
    index="session_date",
    columns="ticker",
    values="daily_price_return",
).reindex(columns=tickers).sort_index()

if returns.isna().any().any():
    raise SystemExit("Some tickers are missing matched return dates.")

if not np.isfinite(returns.to_numpy(dtype=float)).all():
    raise SystemExit("Nonfinite return values found.")

if (returns.std() == 0).any():
    raise SystemExit("A constant return series cannot be correlated.")

correlations = returns.corr(method="pearson")

plt.style.use("default")
figure, axis = plt.subplots(figsize=(13, 11))

heatmap = axis.imshow(
    correlations.to_numpy(),
    cmap="RdBu",
    vmin=-1,
    vmax=1,
)

axis.set_xticks(range(len(tickers)), labels=tickers)
axis.set_yticks(range(len(tickers)), labels=tickers)
plt.setp(
    axis.get_xticklabels(),
    rotation=45,
    ha="right",
    rotation_mode="anchor",
)

for row in range(len(tickers)):
    for column in range(len(tickers)):
        value = correlations.iloc[row, column]
        axis.text(
            column,
            row,
            f"{value:.2f}",
            ha="center",
            va="center",
            fontsize=8,
            color="white" if abs(value) >= 0.6 else "#111827",
        )

colorbar = figure.colorbar(heatmap, ax=axis, shrink=0.8)
colorbar.set_label("Pearson correlation of daily price returns")

start_date = returns.index.min().date()
end_date = returns.index.max().date()

axis.set_title(
    "Daily Return Correlations\n"
    f"{start_date} to {end_date} | "
    f"{len(returns):,} matched return dates",
    fontsize=15,
    pad=20,
)

figure.text(
    0.02,
    0.015,
    "Source: Alpaca SIP. Split-adjusted price returns; "
    "dividends excluded. Same-day historical relationships.",
    fontsize=9,
)

figure.tight_layout(rect=(0, 0.045, 1, 1))

image_path = output_folder / "daily_return_correlations.png"
figure.savefig(image_path, dpi=200, bbox_inches="tight")

matrix_path = output_folder / "daily_return_correlations.csv"
correlations.to_csv(matrix_path)

print(f"Tickers: {len(tickers)}")
print(f"Matched return dates: {len(returns):,}")
print(f"Return date range: {start_date} to {end_date}")
print(f"Chart saved: {image_path}")
print(f"Correlation matrix saved: {matrix_path}")

plt.show()
