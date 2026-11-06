CREATE SCHEMA IF NOT EXISTS market;

CREATE TABLE market.price_bars (
    ticker TEXT NOT NULL,
    bar_timestamp TIMESTAMPTZ NOT NULL,
    timeframe TEXT NOT NULL,
    provider TEXT NOT NULL,
    feed TEXT NOT NULL,
    adjustment TEXT NOT NULL,

    open NUMERIC NOT NULL CHECK (open > 0),
    high NUMERIC NOT NULL CHECK (high > 0),
    low NUMERIC NOT NULL CHECK (low > 0),
    close NUMERIC NOT NULL CHECK (close > 0),
    volume BIGINT NOT NULL CHECK (volume >= 0),
    trade_count BIGINT CHECK (trade_count >= 0),
    vwap NUMERIC,

    source_snapshot TEXT NOT NULL,

    PRIMARY KEY (
        ticker, bar_timestamp, timeframe,
        provider, feed, adjustment
    ),

    CHECK (high >= low),
    CHECK (high >= open AND high >= close),
    CHECK (low <= open AND low <= close)
);
