from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


class ForecastResponse(BaseModel):
    model_config = {"from_attributes": True}

    district:          str
    state:             str
    bulletin_date:     date
    rainfall_prob:     Decimal | None
    rainfall_category: str | None       # low | normal | high
    min_temp_c:        Decimal | None
    max_temp_c:        Decimal | None
    humidity_pct:      Decimal | None
    wind_speed_kmh:    Decimal | None
    wind_direction:    str | None
    season_outlook:    str | None
    advisory_text:     str | None
    fetched_at:        datetime
    is_stale:          bool
