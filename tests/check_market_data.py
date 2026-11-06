import os
from pathlib import Path

import requests
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")
base_url = os.getenv("ALPACA_DATA_URL", "").rstrip("/")

if not all([api_key, secret_key, base_url]):
    raise SystemExit("Missing Alpaca settings in .env")

# Keep credentials directed to the expected data service.
if base_url != "https://data.alpaca.markets":
    raise SystemExit("Check ALPACA_DATA_URL in .env")

response = requests.get(
    f"{base_url}/v2/stocks/MSFT/bars",
    headers={
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    },
    params={
        "timeframe": "1Min",
        "start": "2025-01-06T14:30:00Z",
        "end": "2025-01-06T20:59:00Z",
        "feed": "sip",
        "adjustment": "raw",
        "limit": 1000,
    },
    timeout=30,
)

print(f"HTTP status: {response.status_code}")

if response.status_code != 200:
    print(response.text)
    raise SystemExit("Request failed; check the message above.")

data = response.json()
bars = data.get("bars") or []

print(f"Ticker: {data.get('symbol')}")
print(f"Bars returned: {len(bars)}")
print(f"More pages: {bool(data.get('next_page_token'))}")

if bars:
    print(f"First bar: {bars[0]}")
    print(f"Last bar: {bars[-1]}")
else:
    print("Request succeeded but returned no bars.")
