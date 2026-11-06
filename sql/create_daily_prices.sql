CREATE TABLE market.daily_prices (
    ticker TEXT NOT NULL,
    session_date DATE NOT NULL,

    provider TEXT NOT NULL,
    feed TEXT NOT NULL,
    adjustment TEXT NOT NULL
        CHECK (adjustment IN ('raw', 'split', 'split,dividend')),

    open NUMERIC NOT NULL CHECK (open > 0),
    high NUMERIC NOT NULL CHECK (high > 0),
    low NUMERIC NOT NULL CHECK (low > 0),
    close NUMERIC NOT NULL CHECK (close > 0),
    volume NUMERIC NOT NULL CHECK (volume >= 0),

    source_snapshot TEXT NOT NULL,

    PRIMARY KEY (
        ticker, session_date, provider, feed, adjustment
    ),

    CHECK (high >= low),
    CHECK (high >= open AND high >= close),
    CHECK (low <= open AND low <= close)
);
