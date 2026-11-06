from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
snapshot = "20261103T030011526837Z"
file_path = (
    PROJECT_ROOT / "data" / "raw" / "MSFT"
    / snapshot / "bars.parquet"
)

data = pd.read_parquet(file_path)
timestamps = pd.to_datetime(data["t"], utc=True, errors="coerce")
prices = data[["o", "h", "l", "c"]]

invalid_prices = (
    prices.isna().any(axis=1)
    | prices.le(0).any(axis=1)
    | prices.isin([float("inf"), float("-inf")]).any(axis=1)
)

invalid_ohlc = (
    (data["h"] < data["l"])
    | (data["h"] < data["o"])
    | (data["h"] < data["c"])
    | (data["l"] > data["o"])
    | (data["l"] > data["c"])
)

expected = pd.date_range(
    "2025-01-06 14:30:00",
    periods=390,
    freq="min",
    tz="UTC",
)
observed = pd.DatetimeIndex(timestamps.dropna())

print(f"Rows: {len(data)}")
print(f"Duplicate timestamps: {timestamps.dropna().duplicated().sum()}")
print(f"Invalid timestamps: {timestamps.isna().sum()}")
print(f"Missing expected minutes: {len(expected.difference(observed))}")
print(f"Unexpected timestamps: {len(observed.difference(expected))}")
print(f"Invalid price rows: {invalid_prices.sum()}")
print(f"Invalid OHLC relationships: {invalid_ohlc.sum()}")
print(f"Missing volume: {data['v'].isna().sum()}")
print(f"Negative volume: {(data['v'] < 0).sum()}")
print("\nMissing values by column:")
print(data.isna().sum())
