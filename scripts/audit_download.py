import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
COLLECTION_ID = "fa8b8656c9153942"
COLLECTION = ROOT / "data" / "raw" / "full" / COLLECTION_ID

config = json.loads(
    (COLLECTION / "config.json").read_text(encoding="utf-8")
)

months = pd.period_range(
    config["start_date"],
    config["end_date"],
    freq="M",
)

results = []

for ticker in config["tickers"]:
    for month in months:
        batch_dir = COLLECTION / ticker / str(month)
        marker = batch_dir / "complete.json"

        result = {
            "ticker": ticker,
            "month": str(month),
            "status": "failed",
            "rows": 0,
            "detail": "",
        }

        try:
            if not marker.exists():
                raise ValueError("Missing completion marker")

            completed = json.loads(
                marker.read_text(encoding="utf-8")
            )

            parquet = (batch_dir / completed["parquet"]).resolve()

            if not parquet.is_relative_to(batch_dir.resolve()):
                raise ValueError("Parquet path leaves batch folder")

            if not parquet.is_file():
                raise ValueError("Missing Parquet file")

            actual_hash = hashlib.sha256(
                parquet.read_bytes()
            ).hexdigest()

            if actual_hash != completed["sha256"]:
                raise ValueError("Checksum mismatch")

            rows = pq.ParquetFile(parquet).metadata.num_rows

            if rows != completed["row_count"]:
                raise ValueError("Row count differs from completion marker")

            metadata = json.loads(
                (parquet.parent / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )

            if metadata["status"] != "download_complete":
                raise ValueError("Metadata is not marked complete")

            if metadata["ticker"] != ticker:
                raise ValueError("Ticker differs from metadata")

            if metadata["row_count"] != rows:
                raise ValueError("Row count differs from metadata")

            for setting in ("timeframe", "feed", "adjustment"):
                if metadata["parameters"][setting] != config[setting]:
                    raise ValueError(f"Metadata differs: {setting}")

            result["status"] = "passed"
            result["rows"] = rows

        except Exception as error:
            result["detail"] = str(error)

        results.append(result)

report = pd.DataFrame(results)

report_dir = ROOT / "reports" / "full" / COLLECTION_ID
report_dir.mkdir(parents=True, exist_ok=True)
report_path = report_dir / "download_audit.csv"
report.to_csv(report_path, index=False)

passed = report["status"].eq("passed")
verified = report.loc[passed]

print(f"Collection: {COLLECTION_ID}")
print(f"Date range: {config['start_date']} to {config['end_date']}")
print(f"Tickers: {len(config['tickers'])}")
print(f"Expected batches: {len(report)}")
print(f"Passed batches: {int(passed.sum())}")
print(f"Failed batches: {int((~passed).sum())}")
print(f"Verified downloaded rows: {int(verified['rows'].sum()):,}")

print("\nVerified rows by ticker:")
print(
    verified.groupby("ticker")["rows"]
    .sum()
    .to_string()
)

if not passed.all():
    print("\nFailed batches:")
    print(
        report.loc[~passed, ["ticker", "month", "detail"]]
        .to_string(index=False)
    )

print(f"\nReport saved: {report_path}")
