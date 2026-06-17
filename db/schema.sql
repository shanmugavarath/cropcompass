-- =============================================================
-- CropCompass — Master Database Schema
-- PostgreSQL 15 + pgvector
-- Member 1: Data Engineer (WS1 + WS6)
-- =============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";          -- pgvector
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- trigram for fuzzy district search

-- =============================================================
-- TABLE: farmers
-- Farmer profile & context (Task 1.3)
-- =============================================================
CREATE TABLE IF NOT EXISTS farmers (
    farmer_id       UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(200),
    phone           VARCHAR(20),
    district        VARCHAR(100)    NOT NULL,
    state           VARCHAR(100)    NOT NULL,
    soil_type       VARCHAR(50),                  -- loamy, clay, sandy, black, red
    crop_variety    VARCHAR(100),                 -- rice, wheat, maize, cotton, soybean
    growth_stage    VARCHAR(50),                  -- sowing, vegetative, flowering, harvesting
    lang_pref       VARCHAR(20)     NOT NULL DEFAULT 'eng_Latn',
                                                  -- hin_Deva | tam_Taml | tel_Telu | mar_Deva | pan_Guru | eng_Latn
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_stale        BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Staleness: profile older than 90 days → is_stale = TRUE (Task 1.4)

    CONSTRAINT chk_lang_pref CHECK (
        lang_pref IN ('hin_Deva', 'tam_Taml', 'tel_Telu', 'mar_Deva', 'pan_Guru', 'eng_Latn')
    ),
    CONSTRAINT chk_soil_type CHECK (
        soil_type IS NULL OR soil_type IN ('loamy', 'clay', 'sandy', 'black', 'red', 'alluvial', 'laterite')
    ),
    CONSTRAINT chk_growth_stage CHECK (
        growth_stage IS NULL OR growth_stage IN ('sowing', 'germination', 'vegetative', 'flowering', 'fruiting', 'harvesting')
    )
);

CREATE INDEX IF NOT EXISTS idx_farmers_district ON farmers (district);
CREATE INDEX IF NOT EXISTS idx_farmers_is_stale ON farmers (is_stale) WHERE is_stale = TRUE;

-- Auto-update updated_at on row change
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_farmers_updated_at
    BEFORE UPDATE ON farmers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- =============================================================
-- TABLE: imd_advisories
-- IMD GKMS district weather advisories (Task 1.1)
-- =============================================================
CREATE TABLE IF NOT EXISTS imd_advisories (
    id                  SERIAL          PRIMARY KEY,
    district            VARCHAR(100)    NOT NULL,
    state               VARCHAR(100)    NOT NULL,
    bulletin_date       DATE            NOT NULL,
    rainfall_prob       DECIMAL(5, 4),            -- 0.0000 – 1.0000
    rainfall_category   VARCHAR(10),              -- low | normal | high
    min_temp_c          DECIMAL(5, 2),
    max_temp_c          DECIMAL(5, 2),
    humidity_pct        DECIMAL(5, 2),
    wind_speed_kmh      DECIMAL(6, 2),
    wind_direction      VARCHAR(20),
    season_outlook      TEXT,
    advisory_text       TEXT,                     -- full text of the district advisory
    source_url          VARCHAR(1000),
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_stale            BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Staleness threshold: 48 hours (Task 1.4)

    CONSTRAINT uq_advisory_district_date UNIQUE (district, bulletin_date),
    CONSTRAINT chk_rainfall_prob CHECK (
        rainfall_prob IS NULL OR (rainfall_prob >= 0 AND rainfall_prob <= 1)
    ),
    CONSTRAINT chk_rainfall_category CHECK (
        rainfall_category IS NULL OR rainfall_category IN ('low', 'normal', 'high')
    )
);

CREATE INDEX IF NOT EXISTS idx_imd_district ON imd_advisories (district);
CREATE INDEX IF NOT EXISTS idx_imd_bulletin_date ON imd_advisories (bulletin_date DESC);
CREATE INDEX IF NOT EXISTS idx_imd_district_date ON imd_advisories (district, bulletin_date DESC);
CREATE INDEX IF NOT EXISTS idx_imd_is_stale ON imd_advisories (is_stale) WHERE is_stale = TRUE;
CREATE INDEX IF NOT EXISTS idx_imd_fetched_at ON imd_advisories (fetched_at DESC);

-- Trigram index for fuzzy district name search
CREATE INDEX IF NOT EXISTS idx_imd_district_trgm ON imd_advisories USING GIN (district gin_trgm_ops);


-- =============================================================
-- TABLE: pipeline_runs
-- Audit log for IMD scraper runs (Task 1.4 — structlog JSON)
-- =============================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              SERIAL          PRIMARY KEY,
    pipeline_name   VARCHAR(100)    NOT NULL,     -- imd_scraper | staleness_check
    started_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          VARCHAR(20)     NOT NULL DEFAULT 'running',
                                                  -- running | success | partial | failed
    district_count  INT,
    new_records     INT,
    updated_records INT,
    failed_districts JSONB,                       -- ["Tirunelveli", ...]
    error_message   TEXT,
    log_payload     JSONB,                        -- full structlog JSON blob

    CONSTRAINT chk_pipeline_status CHECK (
        status IN ('running', 'success', 'partial', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_name ON pipeline_runs (pipeline_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs (status) WHERE status IN ('failed', 'partial');


-- =============================================================
-- TABLE: imd_districts_ref
-- Reference table for all supported IMD districts (≥ 36)
-- =============================================================
CREATE TABLE IF NOT EXISTS imd_districts_ref (
    id          SERIAL          PRIMARY KEY,
    district    VARCHAR(100)    NOT NULL,
    state       VARCHAR(100)    NOT NULL,
    imd_code    VARCHAR(20),                      -- IMD internal district code
    latitude    DECIMAL(8, 5),
    longitude   DECIMAL(8, 5),
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_district_state UNIQUE (district, state)
);

CREATE INDEX IF NOT EXISTS idx_districts_state ON imd_districts_ref (state);


-- =============================================================
-- Seed: IMD district reference data (≥ 36 districts across states)
-- =============================================================
INSERT INTO imd_districts_ref (district, state, latitude, longitude) VALUES
-- Tamil Nadu
('Chennai',         'Tamil Nadu',       13.08268, 80.27079),
('Coimbatore',      'Tamil Nadu',       11.01184, 76.94997),
('Madurai',         'Tamil Nadu',        9.91940, 78.11939),
('Tirunelveli',     'Tamil Nadu',        8.71393, 77.75684),
('Salem',           'Tamil Nadu',       11.66430, 78.14613),
('Trichy',          'Tamil Nadu',       10.79027, 78.70420),
('Vellore',         'Tamil Nadu',       12.91698, 79.13291),
('Erode',           'Tamil Nadu',       11.34104, 77.72781),
-- Maharashtra
('Mumbai',          'Maharashtra',      19.07283, 72.88261),
('Pune',            'Maharashtra',      18.52043, 73.85674),
('Nagpur',          'Maharashtra',      21.14631, 79.08491),
('Nashik',          'Maharashtra',      19.99727, 73.79096),
('Aurangabad',      'Maharashtra',      19.87627, 75.34360),
-- Uttar Pradesh
('Lucknow',         'Uttar Pradesh',    26.84600, 80.94620),
('Varanasi',        'Uttar Pradesh',    25.31668, 82.97336),
('Agra',            'Uttar Pradesh',    27.17667, 78.00807),
('Allahabad',       'Uttar Pradesh',    25.43451, 81.84624),
-- Punjab
('Ludhiana',        'Punjab',           30.91002, 75.85098),
('Amritsar',        'Punjab',           31.63380, 74.87234),
('Patiala',         'Punjab',           30.33635, 76.38633),
-- Rajasthan
('Jaipur',          'Rajasthan',        26.92207, 75.77876),
('Jodhpur',         'Rajasthan',        26.29351, 73.01635),
('Udaipur',         'Rajasthan',        24.57130, 73.69142),
-- Andhra Pradesh
('Visakhapatnam',   'Andhra Pradesh',   17.68009, 83.21045),
('Vijayawada',      'Andhra Pradesh',   16.50745, 80.64660),
('Guntur',          'Andhra Pradesh',   16.30688, 80.43574),
-- Telangana
('Hyderabad',       'Telangana',        17.38405, 78.45636),
('Warangal',        'Telangana',        17.97800, 79.59880),
-- Karnataka
('Bengaluru',       'Karnataka',        12.97194, 77.59369),
('Mysuru',          'Karnataka',        12.29680, 76.63940),
('Hubballi',        'Karnataka',        15.36478, 75.12400),
-- Madhya Pradesh
('Bhopal',          'Madhya Pradesh',   23.25969, 77.41261),
('Indore',          'Madhya Pradesh',   22.71792, 75.85772),
-- West Bengal
('Kolkata',         'West Bengal',      22.56263, 88.36304),
('Malda',           'West Bengal',      25.01108, 88.14232),
-- Gujarat
('Ahmedabad',       'Gujarat',          23.02580, 72.58727),
('Surat',           'Gujarat',          21.17024, 72.83113)
ON CONFLICT (district, state) DO NOTHING;


-- =============================================================
-- VIEW: latest_advisories
-- Most recent non-stale advisory per district
-- =============================================================
CREATE OR REPLACE VIEW latest_advisories AS
SELECT DISTINCT ON (district)
    id,
    district,
    state,
    bulletin_date,
    rainfall_prob,
    rainfall_category,
    min_temp_c,
    max_temp_c,
    season_outlook,
    advisory_text,
    fetched_at,
    is_stale
FROM imd_advisories
ORDER BY district, bulletin_date DESC, fetched_at DESC;


-- =============================================================
-- FUNCTION: mark_stale_records()
-- Called by APScheduler cron — Task 1.4
-- Staleness thresholds:
--   imd_advisories : 48 hours from fetched_at
--   farmers        : 90 days  from updated_at
-- =============================================================
CREATE OR REPLACE FUNCTION mark_stale_records()
RETURNS JSONB AS $$
DECLARE
    advisory_count  INT;
    farmer_count    INT;
BEGIN
    UPDATE imd_advisories
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND fetched_at < NOW() - INTERVAL '48 hours';
    GET DIAGNOSTICS advisory_count = ROW_COUNT;

    UPDATE farmers
       SET is_stale = TRUE
     WHERE is_stale = FALSE
       AND updated_at < NOW() - INTERVAL '90 days';
    GET DIAGNOSTICS farmer_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'marked_stale_advisories', advisory_count,
        'marked_stale_farmers',    farmer_count,
        'run_at',                  NOW()
    );
END;
$$ LANGUAGE plpgsql;
