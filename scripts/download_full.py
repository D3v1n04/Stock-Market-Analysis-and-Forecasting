import hashlib
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
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
    (ROOT / "config" / "full.json").read_text(encoding="utf-8")
)

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")
base_url = os.getenv("ALPACA_DATA_URL", "").rstrip("/")

if not api_key or not secret_key:
    raise SystemExit("Missing Alpaca credentials.")
if base_url != "https://data.alpaca.markets":
    raise SystemExit("Check ALPACA_DATA_URL.")

start_date = date.fromisoformat(config["start_date"])
end_date = date.fromisoformat(config["end_date"])
if end_date < start_date:
    raise ValueError("Invalid date range.")

# A configuration change creates a separate collection.
config_text = json.dumps(config, sort_keys=True)
collection_id = hashlib.sha256(
    config_text.encode()
).hexdigest()[:16]

collection_dir = ROOT / "data" / "raw" / "full" / collection_id
collection_dir.mkdir(parents=True, exist_ok=True)


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


save_json(collection_dir / "config.json", config)

# Build calendar-month batches, including partial boundary months.
batches = []
current = start_date
while current <= end_date:
    next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = min(end_date, next_month - timedelta(days=1))
    batches.append((current, last_day))
    current = next_month

retry = Retry(
    total=4,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
    raise_on_status=False,
)

eastern = ZoneInfo("America/New_York")

with requests.Session() as session:
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    })

    for ticker in config["tickers"]:
        for first_day, last_day in batches:
            batch_dir = (
                collection_dir / ticker / first_day.strftime("%Y-%m")
            )
            batch_dir.mkdir(parents=True, exist_ok=True)
            complete_path = batch_dir / "complete.json"

            if complete_path.exists():
                completed = json.loads(
                    complete_path.read_text(encoding="utf-8")
                )
                parquet = batch_dir / completed["parquet"]
                actual_hash = hashlib.sha256(
                    parquet.read_bytes()
                ).hexdigest()

                if actual_hash != completed["sha256"]:
                    raise ValueError(f"Saved file changed: {parquet}")

                print(f"SKIP {ticker} {first_day:%Y-%m}", flush=True)
                continue

            attempt_id = datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%S%fZ"
            )
            attempt_dir = batch_dir / attempt_id
            attempt_dir.mkdir(exist_ok=False)

            start = datetime.combine(
                first_day, datetime.min.time(), tzinfo=eastern
            )
            end = datetime.combine(
                last_day + timedelta(days=1),
                datetime.min.time(),
                tzinfo=eastern,
            ) - timedelta(microseconds=1)

            params = {
                "timeframe": config["timeframe"],
                "feed": config["feed"],
                "adjustment": config["adjustment"],
                "start": start.astimezone(timezone.utc).isoformat(),
                "end": end.astimezone(timezone.utc).isoformat(),
                "limit": 10000,
            }
            url = f"{base_url}/v2/stocks/{ticker}/bars"

            metadata = {
                "ticker": ticker,
                "provider": "Alpaca",
                "endpoint": url,
                "parameters": params.copy(),
                "status": "in_progress",
                "pages": [],
            }
            metadata_path = attempt_dir / "metadata.json"
            save_json(metadata_path, metadata)

            bars = []
            seen_tokens = set()

            try:
                while True:
                    # Pace requests; retries also respect Retry-After.
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
                    (attempt_dir / page_name).write_bytes(
                        response.content
                    )
                    metadata["pages"].append({
                        "file": page_name,
                        "http_status": response.status_code,
                        "parameters": params.copy(),
                        "downloaded_at_utc": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    })
                    save_json(metadata_path, metadata)

                    if response.status_code != 200:
                        raise RuntimeError(
                            f"HTTP {response.status_code}; "
                            f"see {attempt_dir / page_name}"
                        )

                    payload = response.json()
                    bars.extend(payload.get("bars") or [])
                    token = payload.get("next_page_token")

                    if not token:
                        break
                    if token in seen_tokens:
                        raise RuntimeError("Repeated pagination token.")
                    seen_tokens.add(token)
                    params["page_token"] = token

                if not bars:
                    raise ValueError(
                        "Empty batch; investigate before marking complete."
                    )

                table = pd.DataFrame(bars)
                parquet = attempt_dir / "bars.parquet"
                table.to_parquet(parquet, index=False)
                pd.testing.assert_frame_equal(
                    table, pd.read_parquet(parquet)
                )

                metadata["status"] = "download_complete"
                metadata["row_count"] = len(table)
                save_json(metadata_path, metadata)

                # Mark complete only after writing and verifying Parquet.
                save_json(complete_path, {
                    "parquet": parquet.relative_to(
                        batch_dir
                    ).as_posix(),
                    "row_count": len(table),
                    "sha256": hashlib.sha256(
                        parquet.read_bytes()
                    ).hexdigest(),
                })

                print(
                    f"SAVED {ticker} {first_day:%Y-%m}: "
                    f"{len(table):,} bars",
                    flush=True,
                )

            except Exception as error:
                metadata["status"] = "failed"
                metadata["error"] = str(error)
                save_json(metadata_path, metadata)
                raise

print(f"\nCollection download complete: {collection_dir}")
