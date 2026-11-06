WITH benchmark_mapping (ticker, sector_etf) AS (
    VALUES
        ('AMZN', 'XLY'),
        ('MSFT', 'XLK'),
        ('ORCL', 'XLK'),
        ('GOOGL', 'XLC'),
        ('META', 'XLC'),
        ('NVDA', 'SMH'),
        ('AMD', 'SMH'),
        ('TSM', 'SMH'),
        ('MU', 'SMH'),
        ('AVGO', 'SMH')
)
SELECT
    stock.ticker,
    mapping.sector_etf,
    COUNT(*) AS matched_return_dates,

    ROUND(
        CORR(
            stock.daily_price_return::double precision,
            market.daily_price_return::double precision
        )::numeric,
        4
    ) AS correlation_with_spy,

    ROUND(
        CORR(
            stock.daily_price_return::double precision,
            sector.daily_price_return::double precision
        )::numeric,
        4
    ) AS correlation_with_sector

FROM benchmark_mapping mapping

JOIN market.daily_price_returns stock
    ON stock.ticker = mapping.ticker

JOIN market.daily_price_returns market
    ON market.ticker = 'SPY'
   AND market.session_date = stock.session_date
   AND market.previous_session_date =
       stock.previous_session_date

JOIN market.daily_price_returns sector
    ON sector.ticker = mapping.sector_etf
   AND sector.session_date = stock.session_date
   AND sector.previous_session_date =
       stock.previous_session_date

WHERE stock.daily_price_return IS NOT NULL
  AND market.daily_price_return IS NOT NULL
  AND sector.daily_price_return IS NOT NULL

GROUP BY stock.ticker, mapping.sector_etf
ORDER BY stock.ticker;
