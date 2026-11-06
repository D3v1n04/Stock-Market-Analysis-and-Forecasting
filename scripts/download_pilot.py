import json
import os
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
    (ROOT / "config" / "pilot.json").read_text(encoding="utf-8")
)

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")
base_url = os.getenv("ALPACA_DATA_URL", "").rstrip("/")

if not api_key or not secret_key:
    raise SystemExit("Missing Alpaca credentials.")

if base_url != "https://data.alpaca.markets":
    raise SystemExit("Check ALPACA_DATA_URL.")

# Convert inclusive Eastern dates into UTC request boundaries.
eastern = ZoneInfo("America/New_York")
start_date = date.fromisoformat(config["start_date"])
end_date = date.fromisoformat(config["end_date"])

if end_date < start_date:
    raise SystemExit("end_date must not precede start_date.")

start = datetime.combine(
    start_date, datetime.min.time(), tzinfo=eastern
)
end = datetime.combine(
    end_date + timedelta(days=1),
    datetime.min.time(),
    tzinfo=eastern,
) - timedelta(microseconds=1)

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
run_dir = ROOT / "data" / "raw" / "pilot" / run_id
run_dir.mkdir(parents=True, exist_ok=False)

def save_json(path, value):
    path.write_text(
        json.dumps(value, indent=2),
        encoding="utf-8",
    )

save_json(run_dir / "config.json", config)

# Retry GET requests on temporary server errors or rate limits.
retry_policy = Retry(
    total=4,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
    raise_on_status=False,
)

with requests.Session() as session:
    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry_policy),
    )
    session.headers.update({
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    })

    for ticker in config["tickers"]:
        ticker_dir = run_dir / ticker
        ticker_dir.mkdir()

        url = f"{base_url}/v2/stocks/{ticker}/bars"
        params = {
            "timeframe": config["timeframe"],
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
            "feed": config["feed"],
            "adjustment": config["adjustment"],
            # Small enough to exercise pagination in our pilot.
            "limit": 1000,
        }

        metadata = {
            "provider": "Alpaca",
            "ticker": ticker,
            "endpoint": url,
            "parameters": params.copy(),
            "status": "in_progress",
            "pages": [],
        }
        metadata_path = ticker_dir / "metadata.json"
        save_json(metadata_path, metadata)

        bars = []
        seen_tokens = set()
        page_number = 1

        try:
            while True:
                response = session.get(
                    url,
                    params=params,
                    timeout=(10, 60),
                    allow_redirects=False,
                )

                page_name = f"page_{page_number:04d}.json"
                (ticker_dir / page_name).write_bytes(response.content)

                metadata["pages"].append({
                    "file": page_name,
                    "http_status": response.status_code,
                    "downloaded_at_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "parameters": params.copy(),
                })
                save_json(metadata_path, metadata)

                if response.status_code != 200:
                    raise RuntimeError(
                        f"HTTP {response.status_code}; "
                        f"see {page_name}"
                    )

                payload = response.json()
                page_bars = payload.get("bars") or []
                bars.extend(page_bars)

                print(
                    f"{ticker}: page {page_number}, "
                    f"{len(page_bars)} bars"
                )

                token = payload.get("next_page_token")
                if not token:
                    break

                if token in seen_tokens:
                    raise RuntimeError("Repeated pagination token.")

                seen_tokens.add(token)
                params["page_token"] = token
                page_number += 1

            if not bars:
                raise RuntimeError("No bars returned.")

            table = pd.DataFrame(bars)
            parquet_path = ticker_dir / "bars.parquet"
            table.to_parquet(parquet_path, index=False)

            pd.testing.assert_frame_equal(
                table,
                pd.read_parquet(parquet_path),
            )

            metadata["status"] = "download_complete"
            metadata["row_count"] = len(table)
            save_json(metadata_path, metadata)

            print(f"{ticker}: saved and verified {len(table)} bars")

        except Exception as error:
            metadata["status"] = "failed"
            metadata["error"] = str(error)
            save_json(metadata_path, metadata)
            raise

print(f"\nPilot download finished: {run_dir}")
