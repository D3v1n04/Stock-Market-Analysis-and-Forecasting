import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

config = json.loads(
    (ROOT / "config" / "daily.json").read_text(encoding="utf-8")
)

base_url = os.getenv("ALPACA_DATA_URL", "").rstrip("/")
api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

if base_url != "https://data.alpaca.markets":
    raise ValueError("Check ALPACA_DATA_URL.")
if not api_key or not secret_key:
    raise ValueError("Missing Alpaca credentials.")
if config["timeframe"] != "1Day":
    raise ValueError("This downloader expects daily bars.")

eastern = ZoneInfo("America/New_York")
start = datetime.fromisoformat(
    config["start_date"]
).replace(tzinfo=eastern)
end = (
    datetime.fromisoformat(config["end_date"])
    .replace(tzinfo=eastern)
    + timedelta(days=1)
    - timedelta(microseconds=1)
)

if end < start:
    raise ValueError("Invalid date range.")

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
output = ROOT / "data" / "raw" / "daily" / run_id
output.mkdir(parents=True, exist_ok=False)


def save_json(path, value):
    path.write_text(
        json.dumps(value, indent=2), encoding="utf-8"
    )


save_json(output / "config.json", config)

retry = Retry(
    total=4,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
    raise_on_status=False,
)

summary = []

with requests.Session() as session:
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    })

    for ticker in config["tickers"]:
        for adjustment in config["adjustments"]:
            label = adjustment.replace(",", "_")
            folder = output / ticker / label
            folder.mkdir(parents=True)

            params = {
                "timeframe": "1Day",
                "start": start.astimezone(timezone.utc).isoformat(),
                "end": end.astimezone(timezone.utc).isoformat(),
                "feed": config["feed"],
                "adjustment": adjustment,
                "limit": 10000,
            }
            url = f"{base_url}/v2/stocks/{ticker}/bars"
            metadata = {
                "provider": "Alpaca",
                "ticker": ticker,
                "endpoint": url,
                "parameters": params.copy(),
                "status": "in_progress",
                "pages": [],
            }

            bars = []
            tokens = set()

            try:
                while True:
                    time.sleep(0.4)
                    response = session.get(
                        url,
                        params=params,
                        timeout=(10, 60),
                        allow_redirects=False,
                    )

                    page_name = (
                        f"page_{len(metadata['pages']) + 1:04d}.json"
                    )
                    (folder / page_name).write_bytes(response.content)

                    metadata["pages"].append({
                        "file": page_name,
                        "http_status": response.status_code,
                        "parameters": params.copy(),
                        "downloaded_at_utc": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    })
                    save_json(folder / "metadata.json", metadata)

                    if response.status_code != 200:
                        raise RuntimeError(
                            f"HTTP {response.status_code}; "
                            f"see {folder / page_name}"
                        )

                    payload = response.json()
                    bars.extend(payload.get("bars") or [])
                    token = payload.get("next_page_token")

                    if not token:
                        break
                    if token in tokens:
                        raise ValueError("Repeated pagination token.")

                    tokens.add(token)
                    params["page_token"] = token

                if not bars:
                    raise ValueError("No daily bars returned.")

                table = pd.DataFrame(bars)
                path = folder / "bars.parquet"
                table.to_parquet(path, index=False)
                pd.testing.assert_frame_equal(
                    table, pd.read_parquet(path)
                )

                metadata["status"] = "download_complete"
                metadata["row_count"] = len(table)
                save_json(folder / "metadata.json", metadata)

                summary.append({
                    "ticker": ticker,
                    "adjustment": adjustment,
                    "rows": len(table),
                })

                print(
                    f"SAVED {ticker} {adjustment}: "
                    f"{len(table):,} daily bars",
                    flush=True,
                )

            except Exception as error:
                metadata["status"] = "failed"
                metadata["error"] = str(error)
                save_json(folder / "metadata.json", metadata)
                raise

pd.DataFrame(summary).to_csv(
    output / "download_summary.csv", index=False
)
print(f"\nDaily download complete: {output}")
