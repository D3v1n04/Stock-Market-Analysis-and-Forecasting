import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

base_url = os.getenv("ALPACA_DATA_URL", "").rstrip("/")
api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

if base_url != "https://data.alpaca.markets":
    raise ValueError("Check ALPACA_DATA_URL.")
if not api_key or not secret_key:
    raise ValueError("Missing Alpaca credentials.")

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
output = ROOT / "data" / "raw" / "rechecks" / run_id
output.mkdir(parents=True, exist_ok=False)

dates = [
    "2021-04-19",
    "2021-10-25",
    "2022-01-24",
    "2022-03-08",
]
eastern = ZoneInfo("America/New_York")
results = []

with requests.Session() as session:
    session.headers.update({
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    })

    for ticker in ["ORCL", "TSM"]:
        for day in dates:
            start = datetime.fromisoformat(
                f"{day}T09:30:00"
            ).replace(tzinfo=eastern)
            end = datetime.fromisoformat(
                f"{day}T15:59:00"
            ).replace(tzinfo=eastern)

            params = {
                "timeframe": "1Min",
                "start": start.astimezone(timezone.utc).isoformat(),
                "end": end.astimezone(timezone.utc).isoformat(),
                "feed": "sip",
                "adjustment": "raw",
                "limit": 1000,
            }

            response = session.get(
                f"{base_url}/v2/stocks/{ticker}/bars",
                params=params,
                timeout=(10, 60),
                allow_redirects=False,
            )

            prefix = f"{ticker}_{day}"
            (output / f"{prefix}_response.json").write_bytes(
                response.content
            )
            (output / f"{prefix}_request.json").write_text(
                json.dumps({
                    "ticker": ticker,
                    "parameters": params,
                    "http_status": response.status_code,
                    "downloaded_at_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }, indent=2),
                encoding="utf-8",
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"{ticker} {day}: HTTP {response.status_code}"
                )

            payload = response.json()
            if payload.get("next_page_token"):
                raise RuntimeError("Unexpected additional page.")

            bars = payload.get("bars") or []
            results.append({
                "ticker": ticker,
                "session_date": day,
                "expected_minutes": 390,
                "returned_bars": len(bars),
            })

report = pd.DataFrame(results)
report.to_csv(output / "summary.csv", index=False)

print(report.to_string(index=False))
print(f"\nRecheck evidence saved: {output}")
