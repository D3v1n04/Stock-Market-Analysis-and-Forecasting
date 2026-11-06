SELECT
    stock.ticker,
    COUNT(*) AS matched_return_dates,

    ROUND(
        REGR_SLOPE(
            stock.daily_price_return::double precision,
            benchmark.daily_price_return::double precision
        )::numeric,
        4
    ) AS beta_to_spy,

    ROUND(
        REGR_R2(
            stock.daily_price_return::double precision,
            benchmark.daily_price_return::double precision
        )::numeric,
        4
    ) AS market_model_r_squared

FROM market.daily_price_returns stock
JOIN market.daily_price_returns benchmark
    ON stock.session_date = benchmark.session_date
   AND stock.previous_session_date =
       benchmark.previous_session_date

WHERE benchmark.ticker = 'SPY'
  AND stock.ticker IN (
      'AMZN', 'MSFT', 'NVDA', 'AMD', 'GOOGL',
      'META', 'TSM', 'MU', 'ORCL', 'AVGO'
  )
  AND stock.daily_price_return IS NOT NULL
  AND benchmark.daily_price_return IS NOT NULL

GROUP BY stock.ticker
ORDER BY beta_to_spy DESC;
