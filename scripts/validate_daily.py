import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = "20261103T153519225212Z"
SOURCE = ROOT / "data" / "raw" / "daily" / SNAPSHOT

config = json.loads(
    (SOURCE / "config.json").read_text(encoding="utf-8")
)

schedule = mcal.get_calendar("NYSE").schedule(
    start_date=config["start_date"],
    end_date=config["end_date"],
)
expected_dates = set(schedule.index.strftime("%Y-%m-%d"))

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
output = ROOT / "reports" / "daily" / SNAPSHOT / run_id
output.mkdir(parents=True, exist_ok=False)
schedule.to_csv(output / "session_schedule.csv")

summaries = []
date_gaps = []
alignment_results = []

for ticker in config["tickers"]:
    dates_by_version = {}

    for adjustment in config["adjustments"]:
        label = adjustment.replace(",", "_")
        folder = SOURCE / ticker / label

        metadata = json.loads(
            (folder / "metadata.json").read_text(encoding="utf-8")
        )
        if (
            metadata["status"] != "download_complete"
            or metadata["ticker"] != ticker
            or metadata["parameters"]["adjustment"] != adjustment
            or metadata["parameters"]["timeframe"] != "1Day"
            or metadata["parameters"]["feed"] != config["feed"]
        ):
            raise ValueError(f"Metadata mismatch: {ticker} {adjustment}")

        data = pd.read_parquet(folder / "bars.parquet")
        if len(data) != metadata["row_count"]:
            raise ValueError(f"Row-count mismatch: {ticker} {adjustment}")

        timestamps = pd.to_datetime(
            data["t"], utc=True, errors="coerce"
        )
        dates = (
            timestamps.dt.tz_convert("America/New_York")
            .dt.strftime("%Y-%m-%d")
        )
        observed_dates = set(dates.dropna())
        dates_by_version[adjustment] = observed_dates

        # Adjusted volume can be fractional: don't impose
        # the raw minute-bar integer-volume rule here.
        numbers = data[["o", "h", "l", "c", "v"]].apply(
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
        invalid_volume = (
            ~np.isfinite(numbers["v"])
            | numbers["v"].lt(0)
        )
        duplicate_dates = dates.notna() & dates.duplicated(
            keep=False
        )
        unexpected_dates = dates.notna() & ~dates.isin(
            expected_dates
        )
        missing_fields = data.isna().any(axis=1)

        issues = (
            timestamps.isna()
            | duplicate_dates
            | unexpected_dates
            | invalid_prices
            | invalid_ohlc
            | invalid_volume
            | missing_fields
        )

        if issues.any():
            evidence = data.loc[issues].copy()
            evidence["invalid_timestamp"] = timestamps.isna()
            evidence["duplicate_session_date"] = duplicate_dates
            evidence["unexpected_session_date"] = unexpected_dates
            evidence["invalid_price"] = invalid_prices
            evidence["invalid_ohlc"] = invalid_ohlc
            evidence["invalid_volume"] = invalid_volume
            evidence["missing_fields"] = missing_fields
            evidence.to_parquet(
                output / f"issues_{ticker}_{label}.parquet",
                index=False,
            )

        missing = expected_dates - observed_dates
        extra = observed_dates - expected_dates

        for day in sorted(missing):
            date_gaps.append({
                "ticker": ticker,
                "adjustment": adjustment,
                "session_date": day,
                "issue": "missing",
            })
        for day in sorted(extra):
            date_gaps.append({
                "ticker": ticker,
                "adjustment": adjustment,
                "session_date": day,
                "issue": "unexpected",
            })

        summaries.append({
            "ticker": ticker,
            "adjustment": adjustment,
            "rows": len(data),
            "expected_sessions": len(expected_dates),
            "missing_sessions": len(missing),
            "unexpected_sessions": len(extra),
            "invalid_timestamps": int(timestamps.isna().sum()),
            "duplicate_date_rows": int(duplicate_dates.sum()),
            "invalid_price_rows": int(invalid_prices.sum()),
            "invalid_ohlc_rows": int(invalid_ohlc.sum()),
            "invalid_volume_rows": int(invalid_volume.sum()),
            "rows_with_missing_fields": int(missing_fields.sum()),
            "rows_with_issues": int(issues.sum()),
        })

    raw_dates = dates_by_version["raw"]
    for adjustment, observed in dates_by_version.items():
        alignment_results.append({
            "ticker": ticker,
            "adjustment": adjustment,
            "dates_match_raw": observed == raw_dates,
            "dates_only_in_raw": len(raw_dates - observed),
            "dates_only_in_version": len(observed - raw_dates),
        })

summary = pd.DataFrame(summaries)
alignment = pd.DataFrame(alignment_results)

summary.to_csv(output / "daily_quality.csv", index=False)
alignment.to_csv(output / "adjustment_date_alignment.csv", index=False)
pd.DataFrame(
    date_gaps,
    columns=["ticker", "adjustment", "session_date", "issue"],
).to_csv(output / "session_gaps.csv", index=False)

print("DAILY QUALITY")
print(summary.to_string(index=False))
print("\nAll versions match their raw trading dates:",
      bool(alignment["dates_match_raw"].all()))
print(f"Total rows with detected issues: {summary['rows_with_issues'].sum()}")
print(f"Missing ticker/version sessions: {summary['missing_sessions'].sum()}")
print(f"\nReports saved: {output}")
