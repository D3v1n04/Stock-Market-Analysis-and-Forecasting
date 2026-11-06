SELECT
    ticker,
    COUNT(daily_price_return) AS return_observations,
    ROUND(
        100 * STDDEV_SAMP(daily_price_return),
        2
    ) AS daily_volatility_pct,
    ROUND(
        100 * STDDEV_SAMP(daily_price_return)
            * SQRT(252::numeric),
        2
    ) AS annualized_volatility_pct
FROM market.daily_price_returns
GROUP BY ticker
ORDER BY annualized_volatility_pct DESC;
