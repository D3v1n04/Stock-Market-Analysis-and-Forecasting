CREATE VIEW market.daily_price_performance AS
SELECT
    ticker,
    session_date,
    provider,
    feed,
    adjustment,
    close,
    daily_price_return,

    FIRST_VALUE(close) OVER stock_history
        AS starting_close,

    100 * close / FIRST_VALUE(close) OVER stock_history
        AS price_index,

    close / FIRST_VALUE(close) OVER stock_history - 1
        AS cumulative_price_return

FROM market.daily_price_returns

WINDOW stock_history AS (
    PARTITION BY ticker, provider, feed, adjustment
    ORDER BY session_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
);
