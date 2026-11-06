import json
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

ROOT = Path(__file__).resolve().parent.parent
RUN_ID = "20261103T040043189419Z"
RAW_DIR = ROOT / "data" / "raw" / "pilot" / RUN_ID

config = json.loads(
    (RAW_DIR / "config.json").read_text(encoding="utf-8")
)

if config["timeframe"] != "1Min":
    raise ValueError("This validator expects one-minute bars.")

calendar = mcal.get_calendar("NYSE")
schedule = calendar.schedule(
    start_date=config["start_date"],
    end_date=config["end_date"],
)

# Minute bars are labelled by their starting time.
expected = pd.DatetimeIndex([], tz="UTC")
session_minutes = {}

for session_date, session in schedule.iterrows():
    minutes = pd.date_range(
        start=session["market_open"],
        end=session["market_close"],
        freq="min",
        inclusive="left",
    )
    session_minutes[str(session_date.date())] = minutes
    expected = expected.union(minutes)

summaries = []
daily_reports = []
missing_reports = []
observed_by_ticker = {}

for ticker in config["tickers"]:
    ticker_dir = RAW_DIR / ticker
    metadata = json.loads(
        (ticker_dir / "metadata.json").read_text(encoding="utf-8")
    )

    if metadata["status"] != "download_complete":
        raise ValueError(f"{ticker}: download is not complete.")

    data = pd.read_parquet(ticker_dir / "bars.parquet")

    if len(data) != metadata["row_count"]:
        raise ValueError(f"{ticker}: row count differs from metadata.")

    timestamps = pd.to_datetime(
        data["t"], utc=True, errors="coerce"
    )

    regular_mask = timestamps.isin(expected)
    regular = data.loc[regular_mask].copy()
    observed = pd.DatetimeIndex(
        timestamps.loc[regular_mask]
    ).unique()
    observed_by_ticker[ticker] = observed

    prices = data[["o", "h", "l", "c"]].apply(
        pd.to_numeric, errors="coerce"
    )
    invalid_prices = (
        ~np.isfinite(prices).all(axis=1)
        | prices.le(0).any(axis=1)
    )

    invalid_ohlc = (
        (prices["h"] < prices["l"])
        | (prices["h"] < prices["o"])
        | (prices["h"] < prices["c"])
        | (prices["l"] > prices["o"])
        | (prices["l"] > prices["c"])
    )

    volume = pd.to_numeric(data["v"], errors="coerce")
    invalid_volume = (
        ~np.isfinite(volume)
        | volume.lt(0)
        | volume.mod(1).ne(0)
    )

    missing = expected.difference(observed)

    summaries.append({
        "ticker": ticker,
        "raw_rows": len(data),
        "regular_session_rows": len(regular),
        "outside_session_or_invalid_timestamp_rows": int(
            (~regular_mask).sum()
        ),
        "invalid_timestamps": int(timestamps.isna().sum()),
        "duplicate_timestamps": int(
            timestamps.dropna().duplicated().sum()
        ),
        "expected_regular_minutes": len(expected),
        "observed_unique_regular_minutes": len(observed),
        "missing_regular_minutes": len(missing),
        "coverage_pct": (
            round(100 * len(observed) / len(expected), 2)
            if len(expected) else None
        ),
        "invalid_price_rows": int(invalid_prices.sum()),
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "invalid_volume_rows": int(invalid_volume.sum()),
        "rows_with_missing_fields": int(
            data.isna().any(axis=1).sum()
        ),
    })

    for timestamp in missing:
        missing_reports.append({
            "ticker": ticker,
            "missing_timestamp_utc": timestamp.isoformat(),
        })

    for session_date, minutes in session_minutes.items():
        present = minutes.intersection(observed)
        daily_reports.append({
            "ticker": ticker,
            "session_date": session_date,
            "expected_minutes": len(minutes),
            "observed_minutes": len(present),
            "missing_minutes": len(minutes.difference(observed)),
        })

# Compare availability at the same expected minute across tickers.
availability = pd.DataFrame({
    ticker: expected.isin(observed)
    for ticker, observed in observed_by_ticker.items()
}, index=expected)
availability.index.name = "bar_timestamp_utc"

summary = pd.DataFrame(summaries)
daily = pd.DataFrame(daily_reports)
missing_table = pd.DataFrame(
    missing_reports,
    columns=["ticker", "missing_timestamp_utc"],
)

# Exclusive creation prevents overwriting an earlier report.
report_dir = ROOT / "reports" / "pilot" / RUN_ID
report_dir.mkdir(parents=True, exist_ok=False)

summary.to_csv(report_dir / "summary.csv", index=False)
daily.to_csv(report_dir / "daily_coverage.csv", index=False)
missing_table.to_csv(
    report_dir / "missing_minutes.csv", index=False
)
availability.to_csv(report_dir / "timestamp_alignment.csv")
schedule.to_csv(report_dir / "session_schedule.csv")

print("Scheduled sessions:")
print(schedule.to_string())

print("\nQuality summary:")
print(summary.to_string(index=False))

print(
    "\nMinutes present for every pilot ticker: "
    f"{int(availability.all(axis=1).sum())} / {len(expected)}"
)
print(f"\nReports saved to: {report_dir}")
