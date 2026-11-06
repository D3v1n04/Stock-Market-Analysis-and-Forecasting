CREATE VIEW market.daily_price_returns AS
WITH previous_prices AS (
    SELECT
        ticker,
        session_date,
        provider,
        feed,
        adjustment,
        close,
        LAG(session_date) OVER stock_history
            AS previous_session_date,
        LAG(close) OVER stock_history
            AS previous_close
    FROM market.daily_prices
    WHERE provider = 'Alpaca'
      AND feed = 'sip'
      AND adjustment = 'split'
    WINDOW stock_history AS (
        PARTITION BY ticker, provider, feed, adjustment
        ORDER BY session_date
    )
)
SELECT
    *,
    close / previous_close - 1 AS daily_price_return
FROM previous_prices;
