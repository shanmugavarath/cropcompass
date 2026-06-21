-- =============================================================
-- CropCompass — Farmer Profile Table
-- Task 1.3: Farmer Profile & Context Schema
-- =============================================================
-- Standalone file: run this after enabling extensions (schema.sql)
-- SUPPORTED_LANGS: hin_Deva | tam_Taml | tel_Telu | mar_Deva | pan_Guru | eng_Latn
-- Staleness: 90 days from updated_at (Task 1.4)
-- =============================================================

CREATE TABLE IF NOT EXISTS farmers (
    -- Primary key (UUID — used as farmer_id in all API routes)
    farmer_id       UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity (optional — farmer may skip name/phone)
    name            VARCHAR(200),
    phone           VARCHAR(20),

    -- Location (required for IMD forecast lookup)
    district        VARCHAR(100)    NOT NULL,
    state           VARCHAR(100)    NOT NULL,

    -- Farm context (required for agronomic recommendations)
    soil_type       VARCHAR(50),
    -- Allowed values: loamy | clay | sandy | black | red | alluvial | laterite

    crop_variety    VARCHAR(100),
    -- Allowed values: rice | wheat | maize | cotton | soybean | sugarcane | pulses | vegetables

    growth_stage    VARCHAR(50),
    -- Allowed values: sowing | germination | vegetative | flowering | fruiting | harvesting

    -- Language preference (FLORES-200 codes)
    lang_pref       VARCHAR(20)     NOT NULL DEFAULT 'eng_Latn',
    -- hin_Deva → Hindi (Devanagari)
    -- tam_Taml → Tamil
    -- tel_Telu → Telugu
    -- mar_Deva → Marathi (Devanagari)
    -- pan_Guru → Punjabi (Gurmukhi)
    -- eng_Latn → English (fallback)

    -- Audit timestamps
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Staleness flag — set TRUE when updated_at < NOW() - 90 days (Task 1.4)
    is_stale        BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Constraints
    CONSTRAINT chk_lang_pref CHECK (
        lang_pref IN ('hin_Deva', 'tam_Taml', 'tel_Telu', 'mar_Deva', 'pan_Guru', 'eng_Latn')
    ),
    CONSTRAINT chk_soil_type CHECK (
        soil_type IS NULL OR soil_type IN (
            'loamy', 'clay', 'sandy', 'black', 'red', 'alluvial', 'laterite'
        )
    ),
    CONSTRAINT chk_crop_variety CHECK (
        crop_variety IS NULL OR crop_variety IN (
            'rice', 'wheat', 'maize', 'cotton', 'soybean',
            'sugarcane', 'pulses', 'vegetables'
        )
    ),
    CONSTRAINT chk_growth_stage CHECK (
        growth_stage IS NULL OR growth_stage IN (
            'sowing', 'germination', 'vegetative',
            'flowering', 'fruiting', 'harvesting'
        )
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_farmers_district     ON farmers (district);
CREATE INDEX IF NOT EXISTS idx_farmers_state        ON farmers (state);
CREATE INDEX IF NOT EXISTS idx_farmers_crop         ON farmers (crop_variety);
CREATE INDEX IF NOT EXISTS idx_farmers_is_stale     ON farmers (is_stale) WHERE is_stale = TRUE;
CREATE INDEX IF NOT EXISTS idx_farmers_updated_at   ON farmers (updated_at DESC);

-- Trigger: auto-update updated_at on any row modification
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
-- Pydantic schema reference (implemented in app/schemas/farmer.py)
-- =============================================================
-- FarmerCreate:
--   district       str  (required)
--   state          str  (required)
--   name           str  (optional)
--   phone          str  (optional)
--   soil_type      Literal[...soils] (optional)
--   crop_variety   Literal[...crops] (optional)
--   growth_stage   Literal[...stages] (optional)
--   lang_pref      Literal[...langs] = 'eng_Latn'
--
-- FarmerResponse:
--   farmer_id      UUID
--   + all FarmerCreate fields
--   created_at     datetime
--   updated_at     datetime
--   is_stale       bool
-- =============================================================
