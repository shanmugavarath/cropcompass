from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel

Verdict    = Literal["SUFFICIENT", "MARGINAL", "INSUFFICIENT", "EXCESS — DRAINAGE RISK", "UNKNOWN"]
Confidence = Literal["high", "medium", "low"]


class HistoricalRainfallStats(BaseModel):
    years_analysed:    int
    annual_avg_mm:     Decimal
    annual_min_mm:     Decimal
    annual_max_mm:     Decimal
    monsoon_avg_mm:    Decimal
    dry_months:        list[int]       # months where avg rainfall < 60mm
    consistency_score: Decimal         # 0.0–1.0; higher = more consistent year-to-year


class SeasonalOutlookInfo(BaseModel):
    season:             str
    forecast_year:      int
    category:           str | None
    prob_below_normal:  Decimal | None
    prob_normal:        Decimal | None
    prob_above_normal:  Decimal | None
    published_at:       date | None


class CropRequirementInfo(BaseModel):
    min_rainfall_mm:       int
    optimal_rainfall_mm:   int
    max_rainfall_mm:       int
    growing_duration_days: int
    water_sensitivity:     str


class CropSuitabilityResponse(BaseModel):
    district:             str
    state:                str
    crop:                 str
    assessment_date:      date

    historical_rainfall:  HistoricalRainfallStats | None
    seasonal_outlook:     SeasonalOutlookInfo | None
    crop_requirement:     CropRequirementInfo

    verdict:              Verdict
    surplus_deficit_mm:   int            # positive = surplus, negative = deficit vs optimal
    confidence:           Confidence
    recommendation:       str
