CREATE VIEW market.performance_summary AS
WITH latest_performance AS (
    SELECT DISTINCT ON (ticker)
        ticker,
        session_date AS end_date,
        cumulative_price_return
    FROM market.daily_price_performance
    ORDER BY ticker, session_date DESC
),
risk AS (
    SELECT
        ticker,
        MIN(session_date) AS start_date,
        COUNT(daily_price_return) AS return_observations,
        STDDEV_SAMP(daily_price_return)
            * SQRT(252::numeric) AS annualized_volatility
    FROM market.daily_price_returns
    GROUP BY ticker
),
drawdowns AS (
    SELECT
        ticker,
        MIN(drawdown) AS maximum_drawdown
    FROM market.daily_price_drawdowns
    GROUP BY ticker
)
SELECT
    p.ticker,
    r.start_date,
    p.end_date,
    r.return_observations,
    p.cumulative_price_return,
    r.annualized_volatility,
    d.maximum_drawdown
FROM latest_performance p
JOIN risk r USING (ticker)
JOIN drawdowns d USING (ticker);
