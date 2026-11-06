CREATE TABLE market.load_history (
    collection_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    batch_month DATE NOT NULL,

    source_snapshot TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,

    raw_rows BIGINT NOT NULL CHECK (raw_rows >= 0),
    regular_rows BIGINT NOT NULL CHECK (regular_rows >= 0),
    inserted_rows BIGINT NOT NULL CHECK (inserted_rows >= 0),
    existing_identical_rows BIGINT NOT NULL
        CHECK (existing_identical_rows >= 0),

    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (collection_id, ticker, batch_month),

    CHECK (
        regular_rows = inserted_rows + existing_identical_rows
    ),
    CHECK (regular_rows <= raw_rows),
    CHECK (EXTRACT(DAY FROM batch_month) = 1)
);
