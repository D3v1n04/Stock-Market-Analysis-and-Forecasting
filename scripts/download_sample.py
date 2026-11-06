import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")
base_url = os.getenv("ALPACA_DATA_URL", "").rstrip("/")

if not api_key or not secret_key:
    raise SystemExit("Missing Alpaca credentials in .env")

if base_url != "https://data.alpaca.markets":
    raise SystemExit("Check ALPACA_DATA_URL in .env")

ticker = "MSFT"
url = f"{base_url}/v2/stocks/{ticker}/bars"

params = {
    "timeframe": "1Min",
    "start": "2025-01-06T14:30:00Z",
    "end": "2025-01-06T20:59:00Z",
    "feed": "sip",
    "adjustment": "raw",
    "limit": 1000,
}

response = requests.get(
    url,
    headers={
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    },
    params=params,
    timeout=30,
)

if response.status_code != 200:
    print(f"HTTP status: {response.status_code}")
    print(response.text)
    raise SystemExit("Download failed.")

downloaded_at = datetime.now(timezone.utc)
snapshot_id = downloaded_at.strftime("%Y%m%dT%H%M%S%fZ")

output_dir = (
    PROJECT_ROOT / "data" / "raw" / ticker / snapshot_id
)
output_dir.mkdir(parents=True, exist_ok=False)

# Preserve the response body before converting it into a table.
(output_dir / "response.json").write_bytes(response.content)

payload = response.json()
bars = payload.get("bars") or []

metadata = {
    "provider": "Alpaca",
    "ticker": ticker,
    "endpoint": url,
    "parameters": params,
    "downloaded_at_utc": downloaded_at.isoformat(),
    "http_status": response.status_code,
    "row_count": len(bars),
    "next_page_token": payload.get("next_page_token"),
}

(output_dir / "metadata.json").write_text(
    json.dumps(metadata, indent=2),
    encoding="utf-8",
)

if payload.get("next_page_token"):
    raise SystemExit(
        "More pages exist. Response saved, but this sample "
        "script does not yet download additional pages."
    )

if not bars:
    raise SystemExit("Response saved, but no bars were returned.")

# Keep provider field names and values in this raw snapshot.
table = pd.DataFrame(bars)
table.to_parquet(output_dir / "bars.parquet", index=False)

# Confirm the saved table matches the table in memory.
saved_table = pd.read_parquet(output_dir / "bars.parquet")
pd.testing.assert_frame_equal(table, saved_table)

print(f"Saved and verified {len(table)} bars for {ticker}")
print(f"Location: {output_dir}")
