-- =============================================================
-- CropCompass — IMD Advisory Table
-- Task 1.1: IMD GKMS Advisory Ingestion Pipeline
-- =============================================================
-- Standalone file: run this after enabling extensions (schema.sql)
-- Source: IMD GKMS (Gramin Krishi Mausam Seva) district bulletins
-- Refresh: APScheduler cron @ 6AM IST daily
-- Staleness: 48 hours (Task 1.4)
-- =============================================================

CREATE TABLE IF NOT EXISTS imd_advisories (
    -- Primary key
    id                  SERIAL          PRIMARY KEY,

    -- Location
    district            VARCHAR(100)    NOT NULL,
    state               VARCHAR(100)    NOT NULL,

    -- Bulletin identifiers
    bulletin_date       DATE            NOT NULL,   -- date the bulletin was issued

    -- Weather data
    rainfall_prob       DECIMAL(5, 4),              -- 0.0 – 1.0  (e.g. 0.7400 = 74%)
    rainfall_category   VARCHAR(10),                -- low | normal | high
    min_temp_c          DECIMAL(5, 2),              -- degrees Celsius
    max_temp_c          DECIMAL(5, 2),              -- degrees Celsius
    humidity_pct        DECIMAL(5, 2),              -- relative humidity %
    wind_speed_kmh      DECIMAL(6, 2),              -- km/h
    wind_direction      VARCHAR(20),                -- NE, SW, etc.

    -- Advisory content
    season_outlook      TEXT,                       -- seasonal forecast narrative
    advisory_text       TEXT,                       -- full district advisory text

    -- Provenance
    source_url          VARCHAR(1000),              -- scraped URL
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Staleness flag (set by mark_stale_records())
    is_stale            BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Constraints
    CONSTRAINT uq_advisory_district_date    UNIQUE (district, bulletin_date),
    CONSTRAINT chk_rainfall_prob            CHECK (rainfall_prob IS NULL OR (rainfall_prob >= 0 AND rainfall_prob <= 1)),
    CONSTRAINT chk_rainfall_category        CHECK (rainfall_category IS NULL OR rainfall_category IN ('low', 'normal', 'high')),
    CONSTRAINT chk_temp_range               CHECK (min_temp_c IS NULL OR max_temp_c IS NULL OR min_temp_c <= max_temp_c),
    CONSTRAINT chk_humidity                 CHECK (humidity_pct IS NULL OR (humidity_pct >= 0 AND humidity_pct <= 100))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_imd_district             ON imd_advisories (district);
CREATE INDEX IF NOT EXISTS idx_imd_state                ON imd_advisories (state);
CREATE INDEX IF NOT EXISTS idx_imd_bulletin_date        ON imd_advisories (bulletin_date DESC);
CREATE INDEX IF NOT EXISTS idx_imd_district_date        ON imd_advisories (district, bulletin_date DESC);
CREATE INDEX IF NOT EXISTS idx_imd_fetched_at           ON imd_advisories (fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_imd_is_stale             ON imd_advisories (is_stale) WHERE is_stale = TRUE;
CREATE INDEX IF NOT EXISTS idx_imd_rainfall_category    ON imd_advisories (rainfall_category, bulletin_date DESC);

-- Trigram index for fuzzy district lookup
CREATE INDEX IF NOT EXISTS idx_imd_district_trgm        ON imd_advisories USING GIN (district gin_trgm_ops);

-- =============================================================
-- UPSERT PATTERN (used by imd_scraper.py)
-- On conflict (district + bulletin_date):
--   Update weather fields and reset is_stale to FALSE.
--   Keep the record with the latest fetched_at (Task 1.4 conflict policy).
-- =============================================================
-- INSERT INTO imd_advisories (
--     district, state, bulletin_date, rainfall_prob, rainfall_category,
--     min_temp_c, max_temp_c, humidity_pct, wind_speed_kmh, wind_direction,
--     season_outlook, advisory_text, source_url
-- ) VALUES (...)
-- ON CONFLICT (district, bulletin_date)
-- DO UPDATE SET
--     rainfall_prob       = EXCLUDED.rainfall_prob,
--     rainfall_category   = EXCLUDED.rainfall_category,
--     min_temp_c          = EXCLUDED.min_temp_c,
--     max_temp_c          = EXCLUDED.max_temp_c,
--     humidity_pct        = EXCLUDED.humidity_pct,
--     wind_speed_kmh      = EXCLUDED.wind_speed_kmh,
--     wind_direction      = EXCLUDED.wind_direction,
--     season_outlook      = EXCLUDED.season_outlook,
--     advisory_text       = EXCLUDED.advisory_text,
--     source_url          = EXCLUDED.source_url,
--     fetched_at          = NOW(),
--     is_stale            = FALSE
-- WHERE imd_advisories.fetched_at < EXCLUDED.fetched_at;
