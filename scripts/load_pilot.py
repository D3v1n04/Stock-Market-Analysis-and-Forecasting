import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RUN_ID = "20261103T040043189419Z"
RAW_DIR = ROOT / "data" / "raw" / "pilot" / RUN_ID
REPORT_DIR = ROOT / "reports" / "pilot" / RUN_ID

load_dotenv(ROOT / ".env")

config = json.loads(
    (RAW_DIR / "config.json").read_text(encoding="utf-8")
)

if config["timeframe"] != "1Min":
    raise ValueError("This loader expects one-minute bars.")

# Use the session schedule saved during validation.
schedule = pd.read_csv(REPORT_DIR / "session_schedule.csv")
expected = pd.DatetimeIndex([], tz="UTC")

for session in schedule.to_dict("records"):
    minutes = pd.date_range(
        pd.to_datetime(session["market_open"], utc=True),
        pd.to_datetime(session["market_close"], utc=True),
        freq="min",
        inclusive="left",
    )
    expected = expected.union(minutes)

if expected.empty:
    raise ValueError("No expected trading minutes.")

insert_sql = """
    INSERT INTO market.price_bars (
        ticker, bar_timestamp, timeframe, provider,
        feed, adjustment, open, high, low, close,
        volume, trade_count, vwap, source_snapshot
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
    );
"""

results = []

# One transaction for all five tickers.
with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        for ticker in config["tickers"]:
            ticker_dir = RAW_DIR / ticker
            metadata = json.loads(
                (ticker_dir / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )

            if metadata["status"] != "download_complete":
                raise ValueError(f"{ticker}: incomplete download.")

            for setting in ("timeframe", "feed", "adjustment"):
                if metadata["parameters"][setting] != config[setting]:
                    raise ValueError(f"{ticker}: mismatched {setting}.")

            if metadata["ticker"] != ticker:
                raise ValueError(f"{ticker}: metadata ticker mismatch.")

            data = pd.read_parquet(ticker_dir / "bars.parquet")

            if len(data) != metadata["row_count"]:
                raise ValueError(f"{ticker}: row count mismatch.")

            timestamps = pd.to_datetime(
                data["t"], utc=True, errors="raise"
            )
            if timestamps.isna().any() or timestamps.duplicated().any():
                raise ValueError(f"{ticker}: missing/duplicate timestamps.")

            regular = data.loc[timestamps.isin(expected)].copy()
            regular["timestamp"] = timestamps.loc[
                timestamps.isin(expected)
            ]

            observed = pd.DatetimeIndex(regular["timestamp"])
            if len(expected.difference(observed)):
                raise ValueError(f"{ticker}: missing regular minutes.")

            numeric_columns = ["o", "h", "l", "c", "v", "n", "vw"]
            values = regular[numeric_columns].apply(
                pd.to_numeric, errors="raise"
            )

            if not np.isfinite(values.to_numpy(dtype=float)).all():
                raise ValueError(f"{ticker}: missing/nonfinite values.")

            if values[["o", "h", "l", "c", "vw"]].le(0).any().any():
                raise ValueError(f"{ticker}: nonpositive price.")

            for column in ("v", "n"):
                if (
                    values[column].lt(0).any()
                    or values[column].mod(1).ne(0).any()
                ):
                    raise ValueError(f"{ticker}: invalid {column}.")

            invalid_ohlc = (
                (values["h"] < values["l"])
                | (values["h"] < values["o"])
                | (values["h"] < values["c"])
                | (values["l"] > values["o"])
                | (values["l"] > values["c"])
            )
            if invalid_ohlc.any():
                raise ValueError(f"{ticker}: invalid OHLC.")

            provider = metadata["provider"]

            cursor.execute(
                """
                SELECT bar_timestamp, open, high, low, close,
                       volume, trade_count, vwap
                FROM market.price_bars
                WHERE ticker = %s AND timeframe = %s
                  AND provider = %s AND feed = %s
                  AND adjustment = %s
                  AND bar_timestamp >= %s
                  AND bar_timestamp <= %s;
                """,
                (
                    ticker, config["timeframe"], provider,
                    config["feed"], config["adjustment"],
                    expected.min().to_pydatetime(),
                    expected.max().to_pydatetime(),
                ),
            )
            existing = {
                row[0]: tuple(row[1:])
                for row in cursor.fetchall()
            }

            pending = []
            matched = 0
            source = ticker_dir.relative_to(ROOT).as_posix()

            for record in regular.to_dict("records"):
                timestamp = record["timestamp"].to_pydatetime()
                bar_values = (
                    Decimal(str(record["o"])),
                    Decimal(str(record["h"])),
                    Decimal(str(record["l"])),
                    Decimal(str(record["c"])),
                    int(record["v"]),
                    int(record["n"]),
                    Decimal(str(record["vw"])),
                )

                if timestamp in existing:
                    if existing[timestamp] != bar_values:
                        raise ValueError(
                            f"{ticker}: existing values differ "
                            f"at {timestamp}. Load cancelled."
                        )
                    matched += 1
                    continue

                pending.append((
                    ticker, timestamp, config["timeframe"],
                    provider, config["feed"], config["adjustment"],
                    *bar_values, source,
                ))

            if pending:
                cursor.executemany(insert_sql, pending)

            results.append({
                "ticker": ticker,
                "source_regular_rows": len(regular),
                "inserted": len(pending),
                "existing_identical": matched,
            })

# Print success only after the transaction commits.
print(pd.DataFrame(results).to_string(index=False))
print("\nPilot load committed successfully.")
