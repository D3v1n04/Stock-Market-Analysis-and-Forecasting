import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = "20261103T153519225212Z"
SOURCE = ROOT / "data" / "raw" / "daily" / SNAPSHOT
REPORT = (
    ROOT / "reports" / "daily" / SNAPSHOT
    / "20261103T165123844997Z"
)

load_dotenv(ROOT / ".env")

config = json.loads(
    (SOURCE / "config.json").read_text(encoding="utf-8")
)
schedule = pd.read_csv(REPORT / "session_schedule.csv")
expected_dates = set(
    pd.to_datetime(schedule.iloc[:, 0]).dt.date
)

results = []

columns = """
    ticker, session_date, provider, feed, adjustment,
    open, high, low, close, volume, source_snapshot
"""

key_join = """
    p.ticker = s.ticker
    AND p.session_date = s.session_date
    AND p.provider = s.provider
    AND p.feed = s.feed
    AND p.adjustment = s.adjustment
"""

# One transaction: either every version loads, or none does.
with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE market.daily_prices "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
        cursor.execute("""
            CREATE TEMP TABLE incoming_daily
            (LIKE market.daily_prices INCLUDING ALL)
            ON COMMIT DROP
        """)

        for ticker in config["tickers"]:
            for adjustment in config["adjustments"]:
                label = adjustment.replace(",", "_")
                folder = SOURCE / ticker / label

                metadata = json.loads(
                    (folder / "metadata.json").read_text(
                        encoding="utf-8"
                    )
                )

                if (
                    metadata["status"] != "download_complete"
                    or metadata["ticker"] != ticker
                    or metadata["provider"] != "Alpaca"
                    or metadata["parameters"]["adjustment"] != adjustment
                    or metadata["parameters"]["feed"] != config["feed"]
                    or metadata["parameters"]["timeframe"] != "1Day"
                ):
                    raise ValueError("Unexpected source metadata.")

                data = pd.read_parquet(folder / "bars.parquet")
                if len(data) != metadata["row_count"]:
                    raise ValueError("Source row-count mismatch.")

                timestamps = pd.to_datetime(
                    data["t"], utc=True, errors="raise"
                )
                dates = timestamps.dt.tz_convert(
                    "America/New_York"
                ).dt.date

                if (
                    timestamps.isna().any()
                    or dates.duplicated().any()
                    or set(dates) != expected_dates
                ):
                    raise ValueError(
                        f"Session-date mismatch: {ticker} {adjustment}"
                    )

                values = data[["o", "h", "l", "c", "v"]].apply(
                    pd.to_numeric, errors="raise"
                )
                if not np.isfinite(
                    values.to_numpy(dtype=float)
                ).all():
                    raise ValueError("Missing/nonfinite numeric value.")

                if (
                    values[["o", "h", "l", "c"]].le(0).any().any()
                    or values["v"].lt(0).any()
                ):
                    raise ValueError("Invalid price or volume.")

                cursor.execute("TRUNCATE incoming_daily")

                source_snapshot = folder.relative_to(ROOT).as_posix()

                with cursor.copy(
                    f"COPY incoming_daily ({columns}) FROM STDIN"
                ) as copy:
                    for record, day in zip(
                        data.to_dict("records"), dates
                    ):
                        copy.write_row((
                            ticker,
                            day,
                            metadata["provider"],
                            config["feed"],
                            adjustment,
                            Decimal(str(record["o"])),
                            Decimal(str(record["h"])),
                            Decimal(str(record["l"])),
                            Decimal(str(record["c"])),
                            Decimal(str(record["v"])),
                            source_snapshot,
                        ))

                cursor.execute(f"""
                    SELECT s.session_date
                    FROM incoming_daily s
                    JOIN market.daily_prices p ON {key_join}
                    WHERE ROW(
                        p.open, p.high, p.low, p.close, p.volume
                    ) IS DISTINCT FROM ROW(
                        s.open, s.high, s.low, s.close, s.volume
                    )
                    LIMIT 1
                """)

                conflict = cursor.fetchone()
                if conflict:
                    raise ValueError(
                        f"Existing values differ: "
                        f"{ticker} {adjustment} {conflict[0]}"
                    )

                cursor.execute(f"""
                    INSERT INTO market.daily_prices ({columns})
                    SELECT
                        s.ticker, s.session_date, s.provider,
                        s.feed, s.adjustment,
                        s.open, s.high, s.low, s.close, s.volume,
                        s.source_snapshot
                    FROM incoming_daily s
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM market.daily_prices p
                        WHERE {key_join}
                    )
                """)

                inserted = cursor.rowcount
                results.append({
                    "ticker": ticker,
                    "adjustment": adjustment,
                    "source_rows": len(data),
                    "inserted": inserted,
                    "existing_identical": len(data) - inserted,
                })

print(pd.DataFrame(results).to_string(index=False))
print("\nDaily load committed successfully.")
