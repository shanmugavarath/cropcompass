-- =============================================================
-- CropCompass — Rainfall Enhancement Schema
-- Task 1.5: Monsoon Outlook & Historical Rainfall
-- =============================================================

-- =============================================================
-- TABLE: crop_water_requirements
-- ICAR static reference — seeded once, updated manually
-- =============================================================
CREATE TABLE IF NOT EXISTS crop_water_requirements (
    id                    SERIAL          PRIMARY KEY,
    crop_name             VARCHAR(100)    NOT NULL UNIQUE,
    min_rainfall_mm       INT             NOT NULL,
    optimal_rainfall_mm   INT             NOT NULL,
    max_rainfall_mm       INT             NOT NULL,
    growing_duration_days INT             NOT NULL,
    kharif_suitable       BOOLEAN         NOT NULL DEFAULT FALSE,
    rabi_suitable         BOOLEAN         NOT NULL DEFAULT FALSE,
    zaid_suitable         BOOLEAN         NOT NULL DEFAULT FALSE,
    water_sensitivity     VARCHAR(10)     NOT NULL DEFAULT 'medium',
    notes                 TEXT,

    CONSTRAINT chk_rainfall_order  CHECK (min_rainfall_mm <= optimal_rainfall_mm AND optimal_rainfall_mm <= max_rainfall_mm),
    CONSTRAINT chk_sensitivity      CHECK (water_sensitivity IN ('high', 'medium', 'low'))
);

-- Seed: ICAR crop water requirements
INSERT INTO crop_water_requirements
    (crop_name, min_rainfall_mm, optimal_rainfall_mm, max_rainfall_mm, growing_duration_days,
     kharif_suitable, rabi_suitable, zaid_suitable, water_sensitivity, notes)
VALUES
    ('sugarcane', 1500, 2000, 2500, 365, TRUE,  FALSE, FALSE, 'high',
     'Requires well-distributed rainfall. Supplemental irrigation critical in dry months. Waterlogging causes root rot.'),
    ('turmeric',  1500, 1800, 2250, 270, TRUE,  FALSE, FALSE, 'high',
     'Needs moist, well-drained soil. Avoid stagnant water. Red/loamy soils preferred.'),
    ('rice',      1200, 1500, 2000, 120, TRUE,  FALSE, FALSE, 'medium',
     'Paddy fields tolerate standing water. Short-duration varieties need less water.'),
    ('wheat',      400,  500,  600, 120, FALSE, TRUE,  FALSE, 'medium',
     'Cool-weather rabi crop. Excess rain causes fungal diseases. Grown mostly in North India.'),
    ('maize',      500,  750, 1000, 100, TRUE,  FALSE, TRUE,  'medium',
     'Sensitive to waterlogging during germination. Drought-tolerant once established.'),
    ('cotton',     600,  900, 1200, 180, TRUE,  FALSE, FALSE, 'low',
     'Deep-rooted; tolerates dry spells. Rain during boll opening causes quality loss.'),
    ('soybean',    600,  800, 1000, 100, TRUE,  FALSE, FALSE, 'low',
     'Nitrogen-fixing legume. Excess moisture at pod-fill stage reduces yield.'),
    ('pulses',     300,  500,  700,  90, TRUE,  TRUE,  FALSE, 'low',
     'Drought-tolerant. Wide variety of crops (lentil, chickpea, moong). Avoid waterlogging.')
ON CONFLICT (crop_name) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_crop_sensitivity ON crop_water_requirements (water_sensitivity);


-- =============================================================
-- TABLE: imd_historical_rainfall
-- Monthly precipitation per district — loaded via Open-Meteo archive API
-- =============================================================
CREATE TABLE IF NOT EXISTS imd_historical_rainfall (
    id                  SERIAL          PRIMARY KEY,
    district            VARCHAR(100)    NOT NULL,
    state               VARCHAR(100)    NOT NULL,
    year                INT             NOT NULL,
    month               INT             NOT NULL,
    rainfall_mm         DECIMAL(8, 2),              -- monthly total precipitation
    normal_rainfall_mm  DECIMAL(8, 2),              -- 30-yr avg for same month (computed)
    departure_pct       DECIMAL(6, 2),              -- ((actual - normal) / normal) * 100
    data_source         VARCHAR(50)     NOT NULL DEFAULT 'open_meteo',
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_stale            BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Staleness threshold: 35 days

    CONSTRAINT uq_historical_district_year_month UNIQUE (district, year, month),
    CONSTRAINT chk_month CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT chk_year  CHECK (year BETWEEN 1900 AND 2100),
    CONSTRAINT chk_rainfall_non_negative CHECK (rainfall_mm IS NULL OR rainfall_mm >= 0)
);

CREATE INDEX IF NOT EXISTS idx_hist_district       ON imd_historical_rainfall (district);
CREATE INDEX IF NOT EXISTS idx_hist_district_year  ON imd_historical_rainfall (district, year);
CREATE INDEX IF NOT EXISTS idx_hist_year_month     ON imd_historical_rainfall (year, month);
CREATE INDEX IF NOT EXISTS idx_hist_is_stale       ON imd_historical_rainfall (is_stale) WHERE is_stale = TRUE;


-- =============================================================
-- TABLE: imd_seasonal_outlook
-- IMD Long Range Forecast (LRF) — season-level probabilities per district
-- =============================================================
CREATE TABLE IF NOT EXISTS imd_seasonal_outlook (
    id                  SERIAL          PRIMARY KEY,
    district            VARCHAR(100)    NOT NULL,
    state               VARCHAR(100)    NOT NULL,
    forecast_year       INT             NOT NULL,
    season              VARCHAR(20)     NOT NULL,    -- kharif | rabi | annual
    forecast_category   VARCHAR(20),                 -- deficient | below_normal | normal | above_normal | excess
    prob_below_normal   DECIMAL(5, 2),               -- % probability
    prob_normal         DECIMAL(5, 2),               -- % probability
    prob_above_normal   DECIMAL(5, 2),               -- % probability
    published_at        DATE,
    source_url          VARCHAR(1000),
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_stale            BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Staleness threshold: 14 days

    CONSTRAINT uq_outlook_district_year_season UNIQUE (district, forecast_year, season),
    CONSTRAINT chk_season   CHECK (season IN ('kharif', 'rabi', 'annual')),
    CONSTRAINT chk_category CHECK (
        forecast_category IS NULL OR
        forecast_category IN ('deficient', 'below_normal', 'normal', 'above_normal', 'excess')
    )
);

CREATE INDEX IF NOT EXISTS idx_outlook_district       ON imd_seasonal_outlook (district);
CREATE INDEX IF NOT EXISTS idx_outlook_year_season    ON imd_seasonal_outlook (forecast_year, season);
CREATE INDEX IF NOT EXISTS idx_outlook_is_stale       ON imd_seasonal_outlook (is_stale) WHERE is_stale = TRUE;


-- =============================================================
-- EXTEND mark_stale_records() to include new tables
-- =============================================================
CREATE OR REPLACE FUNCTION mark_stale_records()
RETURNS JSONB AS $$
DECLARE
    advisory_count      INT;
    farmer_count        INT;
    historical_count    INT;
    outlook_count       INT;
BEGIN
    -- imd_advisories: stale after 48 hours
    UPDATE imd_advisories
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND fetched_at < NOW() - INTERVAL '48 hours';
    GET DIAGNOSTICS advisory_count = ROW_COUNT;

    -- farmers: stale after 90 days
    UPDATE farmers
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND updated_at < NOW() - INTERVAL '90 days';
    GET DIAGNOSTICS farmer_count = ROW_COUNT;

    -- imd_historical_rainfall: stale after 35 days (one month gap)
    UPDATE imd_historical_rainfall
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND fetched_at < NOW() - INTERVAL '35 days';
    GET DIAGNOSTICS historical_count = ROW_COUNT;

    -- imd_seasonal_outlook: stale after 14 days
    UPDATE imd_seasonal_outlook
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND fetched_at < NOW() - INTERVAL '14 days';
    GET DIAGNOSTICS outlook_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'marked_stale_advisories',         advisory_count,
        'marked_stale_farmers',            farmer_count,
        'marked_stale_historical_rainfall', historical_count,
        'marked_stale_seasonal_outlook',   outlook_count,
        'run_at',                          NOW()
    );
END;
$$ LANGUAGE plpgsql;


-- =============================================================
-- VIEW: district_rainfall_summary
-- Pre-aggregated annual stats per district (used by crop-suitability endpoint)
-- =============================================================
CREATE OR REPLACE VIEW district_rainfall_summary AS
SELECT
    district,
    state,
    COUNT(DISTINCT year)                                    AS years_analysed,
    ROUND(AVG(annual_total), 1)                            AS annual_avg_mm,
    MIN(annual_total)                                       AS annual_min_mm,
    MAX(annual_total)                                       AS annual_max_mm,
    ROUND(AVG(monsoon_total), 1)                           AS monsoon_avg_mm,
    ROUND(
        CASE WHEN AVG(annual_total) > 0
             THEN 1.0 - (STDDEV(annual_total) / AVG(annual_total))
             ELSE 0
        END, 3
    )                                                       AS consistency_score
FROM (
    SELECT
        district,
        state,
        year,
        SUM(rainfall_mm)                                                    AS annual_total,
        SUM(CASE WHEN month BETWEEN 6 AND 10 THEN rainfall_mm ELSE 0 END)  AS monsoon_total
    FROM imd_historical_rainfall
    WHERE is_stale = FALSE
    GROUP BY district, state, year
) yearly
GROUP BY district, state;
