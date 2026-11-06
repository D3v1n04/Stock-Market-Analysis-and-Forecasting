CREATE VIEW market.daily_price_drawdowns AS
WITH running_peaks AS (
    SELECT
        ticker,
        session_date,
        provider,
        feed,
        adjustment,
        close,
        MAX(close) OVER (
            PARTITION BY ticker, provider, feed, adjustment
            ORDER BY session_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_peak_close
    FROM market.daily_price_returns
)
SELECT
    *,
    close / running_peak_close - 1 AS drawdown
FROM running_peaks;
