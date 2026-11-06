import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

ROOT = Path(__file__).resolve().parent.parent
COLLECTION_ID = "fa8b8656c9153942"
COLLECTION = ROOT / "data" / "raw" / "full" / COLLECTION_ID

config = json.loads(
    (COLLECTION / "config.json").read_text(encoding="utf-8")
)

if config["timeframe"] != "1Min":
    raise ValueError("This validator expects one-minute bars.")

# A separate folder preserves each validation run.
validation_id = datetime.now(timezone.utc).strftime(
    "%Y%m%dT%H%M%S%fZ"
)
output = (
    ROOT / "reports" / "full" / COLLECTION_ID
    / "validation" / validation_id
)
output.mkdir(parents=True, exist_ok=False)

schedule = mcal.get_calendar("NYSE").schedule(
    start_date=config["start_date"],
    end_date=config["end_date"],
)
schedule.to_csv(output / "session_schedule.csv")

months = pd.period_range(
    config["start_date"], config["end_date"], freq="M"
)

# Build expected minute starts for each scheduled session.
sessions = {}
for day, session in schedule.iterrows():
    sessions[str(day.date())] = pd.date_range(
        session["market_open"],
        session["market_close"],
        freq="min",
        inclusive="left",
    )

summaries = []
daily_rows = []
availability = {}

for ticker in config["tickers"]:
    ticker_observed = pd.DatetimeIndex([], tz="UTC")

    for month in months:
        batch_dir = COLLECTION / ticker / str(month)
        marker = json.loads(
            (batch_dir / "complete.json").read_text(encoding="utf-8")
        )
        parquet = (batch_dir / marker["parquet"]).resolve()

        if not parquet.is_relative_to(batch_dir.resolve()):
            raise ValueError("Unexpected Parquet path.")

        data = pd.read_parquet(parquet)
        timestamps = pd.to_datetime(
            data["t"], utc=True, errors="coerce"
        )

        expected = pd.DatetimeIndex([], tz="UTC")
        month_sessions = {
            day: minutes
            for day, minutes in sessions.items()
            if day.startswith(str(month))
        }

        for minutes in month_sessions.values():
            expected = expected.union(minutes)

        in_regular = timestamps.isin(expected)
        observed = pd.DatetimeIndex(
            timestamps.loc[in_regular]
        ).unique()
        ticker_observed = ticker_observed.union(observed)

        numeric_columns = ["o", "h", "l", "c", "v", "n", "vw"]
        numbers = data[numeric_columns].apply(
            pd.to_numeric, errors="coerce"
        )
        prices = numbers[["o", "h", "l", "c"]]

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

        invalid_counts = pd.Series(False, index=data.index)
        for column in ("v", "n"):
            values = numbers[column]
            invalid_counts |= (
                ~np.isfinite(values)
                | values.lt(0)
                | values.mod(1).ne(0)
            )

        invalid_vwap = (
            ~np.isfinite(numbers["vw"])
            | numbers["vw"].le(0)
        )
        duplicate = (
            timestamps.notna()
            & timestamps.duplicated(keep=False)
        )

        # Verify that valid timestamps belong to this requested month.
        local_month = (
            timestamps.dt.tz_convert("America/New_York")
            .dt.strftime("%Y-%m")
        )
        wrong_month = timestamps.notna() & local_month.ne(str(month))

        issue_mask = (
            timestamps.isna()
            | duplicate
            | invalid_prices
            | invalid_ohlc
            | invalid_counts
            | invalid_vwap
            | wrong_month
        )

        if issue_mask.any():
            evidence = data.loc[issue_mask].copy()
            evidence["invalid_timestamp"] = timestamps.isna()
            evidence["duplicate_timestamp"] = duplicate
            evidence["invalid_price"] = invalid_prices
            evidence["invalid_ohlc"] = invalid_ohlc
            evidence["invalid_volume_or_trade_count"] = invalid_counts
            evidence["invalid_vwap"] = invalid_vwap
            evidence["wrong_month"] = wrong_month
            evidence["is_regular_session"] = in_regular

            evidence.to_parquet(
                output / f"issues_{ticker}_{month}.parquet",
                index=False,
            )

        missing = expected.difference(observed)
        if len(missing):
            pd.DataFrame({
                "ticker": ticker,
                "missing_timestamp_utc": missing,
            }).to_csv(
                output / f"missing_{ticker}_{month}.csv",
                index=False,
            )

        summaries.append({
            "ticker": ticker,
            "month": str(month),
            "raw_rows": len(data),
            "regular_rows": int(in_regular.sum()),
            "outside_regular_valid_timestamp_rows": int(
                (timestamps.notna() & ~in_regular).sum()
            ),
            "invalid_timestamps": int(timestamps.isna().sum()),
            "duplicate_timestamp_rows": int(duplicate.sum()),
            "wrong_month_rows": int(wrong_month.sum()),
            "expected_minutes": len(expected),
            "observed_unique_minutes": len(observed),
            "missing_minutes": len(missing),
            "invalid_price_rows": int(invalid_prices.sum()),
            "invalid_ohlc_rows": int(invalid_ohlc.sum()),
            "invalid_volume_or_trade_count_rows": int(
                invalid_counts.sum()
            ),
            "invalid_vwap_rows": int(invalid_vwap.sum()),
            "rows_with_issues": int(issue_mask.sum()),
            "regular_rows_with_issues": int(
                (issue_mask & in_regular).sum()
            ),
        })

        for day, minutes in month_sessions.items():
            daily_rows.append({
                "ticker": ticker,
                "session_date": day,
                "expected_minutes": len(minutes),
                "observed_minutes": len(minutes.intersection(observed)),
                "missing_minutes": len(minutes.difference(observed)),
            })

        print(f"CHECKED {ticker} {month}", flush=True)

    availability[ticker] = ticker_observed

summary = pd.DataFrame(summaries)
summary.to_csv(output / "monthly_quality.csv", index=False)
pd.DataFrame(daily_rows).to_csv(
    output / "daily_coverage.csv", index=False
)

# Presence matrix: compare all tickers at each scheduled minute.
all_expected = pd.DatetimeIndex([], tz="UTC")
for minutes in sessions.values():
    all_expected = all_expected.union(minutes)

alignment = pd.DataFrame({
    ticker: all_expected.isin(observed)
    for ticker, observed in availability.items()
}, index=all_expected)
alignment.index.name = "bar_timestamp_utc"
alignment.to_parquet(output / "timestamp_alignment.parquet")

totals = summary.groupby("ticker").sum(numeric_only=True)
totals["coverage_pct"] = (
    100 * totals["observed_unique_minutes"]
    / totals["expected_minutes"]
).round(4)
totals.to_csv(output / "ticker_quality.csv")

print("\nQUALITY TOTALS")
print(totals.to_string())
print(
    "\nMinutes present for all 15 tickers: "
    f"{int(alignment.all(axis=1).sum()):,} / "
    f"{len(all_expected):,}"
)
print(f"\nReports saved: {output}")
