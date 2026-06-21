from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://cropcompass:cropcompass_secret@localhost:5432/cropcompass"
    database_url_sync: str = "postgresql+psycopg2://cropcompass:cropcompass_secret@localhost:5432/cropcompass"

    # Anthropic
    anthropic_api_key: str = ""

    # HuggingFace
    hf_api_key: str = ""
    hf_inference_endpoint: str = "https://api-inference.huggingface.co/models/ai4bharat/indictrans2-en-indic-1B"

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # Logging
    log_level: str = "INFO"

    # IMD scraper
    imd_gkms_base_url: str = "https://mausam.imd.gov.in/responsive/agromet_adv_ser_district_current_en.php"
    imd_scraper_cron_hour: int = 6
    imd_scraper_cron_minute: int = 0
    imd_scraper_timezone: str = "Asia/Kolkata"
    imd_scraper_request_timeout: int = 30       # seconds per district request
    imd_scraper_concurrency: int = 5            # concurrent district fetches
    imd_dev_mock: bool = Field(default=False)   # set True to use mock data in dev

    # Staleness thresholds
    imd_staleness_hours: int = 48
    farmer_staleness_days: int = 90
    icar_staleness_days: int = 180


settings = Settings()
