import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

snapshot = "20261103T030011526837Z"
snapshot_dir = PROJECT_ROOT / "data" / "raw" / "MSFT" / snapshot

data = pd.read_parquet(snapshot_dir / "bars.parquet")
metadata = json.loads(
    (snapshot_dir / "metadata.json").read_text(encoding="utf-8")
)

if len(data) != metadata["row_count"]:
    raise ValueError("Parquet row count does not match metadata.")

if data.empty:
    raise ValueError("No rows to load.")

timestamps = pd.to_datetime(data["t"], utc=True, errors="raise")

if timestamps.isna().any() or timestamps.duplicated().any():
    raise ValueError("Missing or duplicate timestamps.")

source_snapshot = snapshot_dir.relative_to(PROJECT_ROOT).as_posix()
params = metadata["parameters"]


def decimal_or_none(value):
    return None if pd.isna(value) else Decimal(str(value))


rows = []

for record, timestamp in zip(data.to_dict("records"), timestamps):
    rows.append((
        metadata["ticker"],
        timestamp.to_pydatetime(),
        params["timeframe"],
        metadata["provider"],
        params["feed"],
        params["adjustment"],
        decimal_or_none(record["o"]),
        decimal_or_none(record["h"]),
        decimal_or_none(record["l"]),
        decimal_or_none(record["c"]),
        int(record["v"]),
        None if pd.isna(record.get("n")) else int(record["n"]),
        decimal_or_none(record.get("vw")),
        source_snapshot,
    ))

insert_sql = """
    INSERT INTO market.price_bars (
        ticker, bar_timestamp, timeframe, provider,
        feed, adjustment,
        open, high, low, close,
        volume, trade_count, vwap, source_snapshot
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (
        ticker, bar_timestamp, timeframe,
        provider, feed, adjustment
    ) DO NOTHING;
"""

with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.executemany(insert_sql, rows)
        inserted = cursor.rowcount

# The connection context commits only if the operation succeeds.
print(f"Source rows: {len(rows)}")
print(f"Inserted rows: {inserted}")
print(f"Existing keys skipped: {len(rows) - inserted}")
