import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
COLLECTION_ID = "fa8b8656c9153942"
COLLECTION = ROOT / "data" / "raw" / "full" / COLLECTION_ID
VALIDATION = (
    ROOT / "reports" / "full" / COLLECTION_ID
    / "validation" / "20261103T051507087954Z"
)

load_dotenv(ROOT / ".env")

config = json.loads(
    (COLLECTION / "config.json").read_text(encoding="utf-8")
)
quality = pd.read_csv(VALIDATION / "monthly_quality.csv")
schedule = pd.read_csv(VALIDATION / "session_schedule.csv")

if config["timeframe"] != "1Min":
    raise ValueError("This loader expects one-minute bars.")

months = pd.period_range(
    config["start_date"], config["end_date"], freq="M"
)

# Require exactly one validation result per requested batch.
expected_keys = {
    (ticker, str(month))
    for ticker in config["tickers"]
    for month in months
}
report_keys = list(zip(quality["ticker"], quality["month"]))

if len(report_keys) != len(set(report_keys)):
    raise ValueError("Duplicate batches in validation report.")
if set(report_keys) != expected_keys:
    raise ValueError("Validation report does not match collection.")

quality = quality.set_index(["ticker", "month"])

# The current collection reported zero issues.
# Stop if that changes rather than silently dropping invalid records.
if quality["rows_with_issues"].sum() != 0:
    raise ValueError("Resolve reported record issues before loading.")

expected_by_month = {}
for record in schedule.to_dict("records"):
    start = pd.to_datetime(record["market_open"], utc=True)
    end = pd.to_datetime(record["market_close"], utc=True)
    month = start.tz_convert("America/New_York").strftime("%Y-%m")
    minutes = pd.date_range(
        start, end, freq="min", inclusive="left"
    )
    previous = expected_by_month.get(
        month, pd.DatetimeIndex([], tz="UTC")
    )
    expected_by_month[month] = previous.union(minutes)

columns = """
    ticker, bar_timestamp, timeframe, provider, feed, adjustment,
    open, high, low, close, volume, trade_count, vwap,
    source_snapshot
"""

key_join = """
    p.ticker = s.ticker
    AND p.bar_timestamp = s.bar_timestamp
    AND p.timeframe = s.timeframe
    AND p.provider = s.provider
    AND p.feed = s.feed
    AND p.adjustment = s.adjustment
"""

value_difference = """
    ROW(p.open, p.high, p.low, p.close,
        p.volume, p.trade_count, p.vwap)
    IS DISTINCT FROM
    ROW(s.open, s.high, s.low, s.close,
        s.volume, s.trade_count, s.vwap)
"""

inserted_total = 0
matched_total = 0
skipped_batches = 0

# Autocommit allows an explicit, separate transaction per batch.
with psycopg.connect(
    connect_timeout=10, autocommit=True
) as connection:
    for ticker in config["tickers"]:
        for month in months:
            month_text = str(month)
            batch_month = date(month.year, month.month, 1)
            batch_dir = COLLECTION / ticker / month_text

            marker = json.loads(
                (batch_dir / "complete.json").read_text(
                    encoding="utf-8"
                )
            )
            parquet = (batch_dir / marker["parquet"]).resolve()
            if not parquet.is_relative_to(batch_dir.resolve()):
                raise ValueError("Unexpected source path.")

            checksum = hashlib.sha256(
                parquet.read_bytes()
            ).hexdigest()
            if checksum != marker["sha256"]:
                raise ValueError(f"Checksum mismatch: {parquet}")

            with connection.transaction():
                with connection.cursor() as cursor:
                    # Serialize loaders using this table so overlap
                    # comparisons and insertion cannot race.
                    cursor.execute(
                        "LOCK TABLE market.price_bars "
                        "IN SHARE ROW EXCLUSIVE MODE"
                    )

                    cursor.execute(
                        """
                        SELECT source_sha256
                        FROM market.load_history
                        WHERE collection_id = %s
                          AND ticker = %s AND batch_month = %s
                        """,
                        (COLLECTION_ID, ticker, batch_month),
                    )
                    history = cursor.fetchone()

                    if history:
                        if history[0] != checksum:
                            raise ValueError(
                                f"Loaded source changed: {ticker} {month}"
                            )
                        skipped_batches += 1
                        print(
                            f"SKIP {ticker} {month}: previously committed",
                            flush=True,
                        )
                        continue

                    metadata = json.loads(
                        (parquet.parent / "metadata.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    if (
                        metadata["status"] != "download_complete"
                        or metadata["ticker"] != ticker
                        or metadata["provider"] != "Alpaca"
                    ):
                        raise ValueError("Unexpected batch metadata.")

                    for setting in ("timeframe", "feed", "adjustment"):
                        if metadata["parameters"][setting] != config[setting]:
                            raise ValueError(f"Mismatched {setting}.")

                    data = pd.read_parquet(parquet)
                    report = quality.loc[(ticker, month_text)]

                    if not (
                        len(data)
                        == marker["row_count"]
                        == metadata["row_count"]
                        == int(report["raw_rows"])
                    ):
                        raise ValueError("Source/report row count mismatch.")

                    timestamps = pd.to_datetime(
                        data["t"], utc=True, errors="raise"
                    )
                    if (
                        timestamps.isna().any()
                        or timestamps.duplicated().any()
                    ):
                        raise ValueError("Missing/duplicate timestamps.")

                    if not timestamps.dt.tz_convert(
                        "America/New_York"
                    ).dt.strftime("%Y-%m").eq(month_text).all():
                        raise ValueError("Timestamp outside batch month.")

                    expected = expected_by_month[month_text]
                    regular = data.loc[timestamps.isin(expected)].copy()
                    regular["timestamp"] = timestamps.loc[
                        timestamps.isin(expected)
                    ]

                    if len(regular) != int(report["regular_rows"]):
                        raise ValueError("Regular-session count mismatch.")

                    values = regular[
                        ["o", "h", "l", "c", "v", "n", "vw"]
                    ].apply(pd.to_numeric, errors="raise")

                    if not np.isfinite(
                        values.to_numpy(dtype=float)
                    ).all():
                        raise ValueError("Missing/nonfinite numeric value.")

                    if values[["o", "h", "l", "c", "vw"]].le(
                        0
                    ).any().any():
                        raise ValueError("Nonpositive price.")

                    for name in ("v", "n"):
                        if (
                            values[name].lt(0).any()
                            or values[name].mod(1).ne(0).any()
                        ):
                            raise ValueError("Invalid volume/trade count.")

                    # Temp table inherits price-table constraints.
                    cursor.execute("""
                        CREATE TEMP TABLE incoming_bars
                        (LIKE market.price_bars INCLUDING ALL)
                        ON COMMIT DROP
                    """)

                    source = parquet.parent.relative_to(
                        ROOT
                    ).as_posix()

                    with cursor.copy(
                        f"COPY incoming_bars ({columns}) FROM STDIN"
                    ) as copy:
                        for row in regular.to_dict("records"):
                            copy.write_row((
                                ticker,
                                row["timestamp"].to_pydatetime(),
                                config["timeframe"],
                                metadata["provider"],
                                config["feed"],
                                config["adjustment"],
                                Decimal(str(row["o"])),
                                Decimal(str(row["h"])),
                                Decimal(str(row["l"])),
                                Decimal(str(row["c"])),
                                int(row["v"]),
                                int(row["n"]),
                                Decimal(str(row["vw"])),
                                source,
                            ))

                    cursor.execute(f"""
                        SELECT s.bar_timestamp
                        FROM incoming_bars s
                        JOIN market.price_bars p ON {key_join}
                        WHERE {value_difference}
                        LIMIT 1
                    """)
                    conflict = cursor.fetchone()
                    if conflict:
                        raise ValueError(
                            f"Conflicting existing bar: "
                            f"{ticker} {conflict[0]}"
                        )

                    cursor.execute(f"""
                        INSERT INTO market.price_bars ({columns})
                        SELECT {', '.join(
                            's.' + name.strip()
                            for name in columns.split(',')
                        )}
                        FROM incoming_bars s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM market.price_bars p
                            WHERE {key_join}
                        )
                    """)
                    inserted = cursor.rowcount
                    matched = len(regular) - inserted

                    cursor.execute("""
                        INSERT INTO market.load_history (
                            collection_id, ticker, batch_month,
                            source_snapshot, source_sha256,
                            raw_rows, regular_rows, inserted_rows,
                            existing_identical_rows
                        )
                        VALUES (%s, %s, %s, %s, %s,
                                %s, %s, %s, %s)
                    """, (
                        COLLECTION_ID, ticker, batch_month,
                        source, checksum, len(data), len(regular),
                        inserted, matched,
                    ))

            # Printed only after this batch commits.
            inserted_total += inserted
            matched_total += matched
            print(
                f"COMMITTED {ticker} {month}: "
                f"{inserted:,} inserted, {matched:,} identical",
                flush=True,
            )

print("\nFull load finished.")
print(f"Inserted this run: {inserted_total:,}")
print(f"Existing identical this run: {matched_total:,}")
print(f"Previously committed batches skipped: {skipped_batches}")
