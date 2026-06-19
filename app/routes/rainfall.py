from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.crop_water_req import CropWaterRequirement
from app.models.historical_rainfall import IMDHistoricalRainfall
from app.models.seasonal_outlook import IMDSeasonalOutlook
from app.schemas.rainfall import (
    CropSuitabilityResponse, CropRequirementInfo,
    HistoricalRainfallStats, SeasonalOutlookInfo,
)

router = APIRouter(prefix="/api/rainfall", tags=["rainfall"])

_CURRENT_YEAR = date.today().year
_KHARIF_MONTHS = {6, 7, 8, 9, 10}
_DRY_THRESHOLD_MM = 60


def _current_season() -> str:
    month = date.today().month
    if 6 <= month <= 10:
        return "kharif"
    if 11 <= month <= 3:
        return "rabi"
    return "zaid"


def _compute_verdict(hist_avg: Decimal, crop: CropWaterRequirement, outlook_category: str | None) -> str:
    avg = int(hist_avg)
    if avg > crop.max_rainfall_mm:
        return "EXCESS — DRAINAGE RISK"
    if avg >= crop.optimal_rainfall_mm:
        return "SUFFICIENT"
    if avg >= crop.min_rainfall_mm:
        if outlook_category in ("normal", "above_normal", "excess"):
            return "SUFFICIENT"
        return "MARGINAL"
    # below minimum
    if outlook_category in ("above_normal", "excess"):
        return "MARGINAL"
    return "INSUFFICIENT"


def _confidence(years: int, has_outlook: bool) -> str:
    if years >= 7 and has_outlook:
        return "high"
    if years >= 3:
        return "medium"
    return "low"


def _build_recommendation(
    verdict: str,
    crop_name: str,
    district: str,
    hist_avg: Decimal,
    crop: CropWaterRequirement,
    outlook: SeasonalOutlookInfo | None,
    dry_months: list[int],
) -> str:
    month_names = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                   7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
    dry_str = ", ".join(month_names[m] for m in dry_months) if dry_months else "none"
    deficit = int(hist_avg) - crop.min_rainfall_mm

    outlook_str = ""
    if outlook and outlook.category:
        outlook_str = f" The {outlook.season} {outlook.forecast_year} outlook is {outlook.category.replace('_', ' ')}."

    if verdict == "SUFFICIENT":
        return (
            f"Historical annual average ({int(hist_avg)}mm) meets the {crop_name} requirement "
            f"(minimum {crop.min_rainfall_mm}mm, optimal {crop.optimal_rainfall_mm}mm).{outlook_str} "
            f"Conditions in {district} are suitable. Dry months: {dry_str} — irrigate if available."
        )
    if verdict == "MARGINAL":
        return (
            f"Historical annual average ({int(hist_avg)}mm) is near the minimum for {crop_name} "
            f"({crop.min_rainfall_mm}mm).{outlook_str} "
            f"Plan supplemental irrigation during dry months ({dry_str}) to bridge the shortfall. "
            f"Consider drought-tolerant {crop_name} varieties."
        )
    if verdict == "INSUFFICIENT":
        return (
            f"Historical annual average ({int(hist_avg)}mm) is {abs(deficit)}mm below the minimum "
            f"for {crop_name} ({crop.min_rainfall_mm}mm).{outlook_str} "
            f"{crop_name.capitalize()} cultivation in {district} carries significant water-stress risk. "
            f"Drip irrigation or a different crop is recommended."
        )
    if verdict == "EXCESS — DRAINAGE RISK":
        return (
            f"Historical annual average ({int(hist_avg)}mm) exceeds the maximum safe rainfall "
            f"for {crop_name} ({crop.max_rainfall_mm}mm). Waterlogging risk is high.{outlook_str} "
            f"Ensure raised beds and proper field drainage before planting."
        )
    return "Insufficient data to generate a recommendation."


@router.get("/{district}/crop-suitability/{crop}", response_model=CropSuitabilityResponse)
async def crop_suitability(
    district: str,
    crop: str,
    session: AsyncSession = Depends(get_session),
):
    # ── 1. Validate crop ─────────────────────────────────────────────────────
    crop_lower = crop.lower()
    crop_req = await session.scalar(
        select(CropWaterRequirement).where(
            func.lower(CropWaterRequirement.crop_name) == crop_lower
        )
    )
    if crop_req is None:
        raise HTTPException(status_code=404, detail=f"Crop '{crop}' not found. Supported: sugarcane, turmeric, rice, wheat, maize, cotton, soybean, pulses")

    # ── 2. Historical rainfall stats ──────────────────────────────────────────
    hist_rows = (await session.execute(
        select(IMDHistoricalRainfall).where(
            func.lower(IMDHistoricalRainfall.district) == district.lower(),
            IMDHistoricalRainfall.is_stale == False,
        ).order_by(IMDHistoricalRainfall.year, IMDHistoricalRainfall.month)
    )).scalars().all()

    # Resolve actual district/state name from first row
    actual_district = hist_rows[0].district if hist_rows else district
    actual_state    = hist_rows[0].state    if hist_rows else "Unknown"

    hist_stats: HistoricalRainfallStats | None = None
    hist_avg = Decimal(0)

    if hist_rows:
        # Aggregate by year
        yearly: dict[int, Decimal] = {}
        monsoon_by_year: dict[int, Decimal] = {}
        monthly_totals: dict[int, list[Decimal]] = {m: [] for m in range(1, 13)}

        for row in hist_rows:
            mm = row.rainfall_mm or Decimal(0)
            yearly[row.year] = yearly.get(row.year, Decimal(0)) + mm
            if row.month in _KHARIF_MONTHS:
                monsoon_by_year[row.year] = monsoon_by_year.get(row.year, Decimal(0)) + mm
            monthly_totals[row.month].append(mm)

        annual_values = list(yearly.values())
        hist_avg       = Decimal(sum(annual_values) / len(annual_values))
        monsoon_vals   = list(monsoon_by_year.values())
        monsoon_avg    = Decimal(sum(monsoon_vals) / len(monsoon_vals)) if monsoon_vals else Decimal(0)

        # Dry months: monthly average < 60mm
        monthly_avgs = {
            m: Decimal(sum(vals) / len(vals)) if vals else Decimal(0)
            for m, vals in monthly_totals.items()
        }
        dry_months = sorted(m for m, avg in monthly_avgs.items() if avg < _DRY_THRESHOLD_MM)

        # Consistency score: 1 - (std_dev / mean)
        mean = float(hist_avg)
        if mean > 0 and len(annual_values) > 1:
            variance = sum((float(v) - mean) ** 2 for v in annual_values) / len(annual_values)
            std_dev = variance ** 0.5
            consistency = max(Decimal(0), Decimal(str(round(1 - std_dev / mean, 3))))
        else:
            consistency = Decimal("0.0")

        hist_stats = HistoricalRainfallStats(
            years_analysed=len(yearly),
            annual_avg_mm=Decimal(str(round(hist_avg, 1))),
            annual_min_mm=min(annual_values),
            annual_max_mm=max(annual_values),
            monsoon_avg_mm=Decimal(str(round(monsoon_avg, 1))),
            dry_months=dry_months,
            consistency_score=consistency,
        )

    # ── 3. Seasonal outlook ───────────────────────────────────────────────────
    season = _current_season()
    outlook_row = await session.scalar(
        select(IMDSeasonalOutlook).where(
            func.lower(IMDSeasonalOutlook.district) == district.lower(),
            IMDSeasonalOutlook.forecast_year == _CURRENT_YEAR,
            IMDSeasonalOutlook.season == season,
            IMDSeasonalOutlook.is_stale == False,
        )
    )
    outlook: SeasonalOutlookInfo | None = None
    if outlook_row:
        outlook = SeasonalOutlookInfo(
            season=outlook_row.season,
            forecast_year=outlook_row.forecast_year,
            category=outlook_row.forecast_category,
            prob_below_normal=outlook_row.prob_below_normal,
            prob_normal=outlook_row.prob_normal,
            prob_above_normal=outlook_row.prob_above_normal,
            published_at=outlook_row.published_at,
        )

    # ── 4. Verdict + recommendation ───────────────────────────────────────────
    if hist_stats is None:
        verdict = "UNKNOWN"
        surplus_deficit = 0
        confidence = "low"
        recommendation = f"No historical rainfall data available for {district}. Run the rainfall pipeline first."
    else:
        verdict = _compute_verdict(hist_avg, crop_req, outlook.category if outlook else None)
        surplus_deficit = int(hist_avg) - crop_req.optimal_rainfall_mm
        confidence = _confidence(hist_stats.years_analysed, outlook is not None)
        recommendation = _build_recommendation(
            verdict, crop_req.crop_name, actual_district,
            hist_avg, crop_req, outlook, hist_stats.dry_months
        )

    return CropSuitabilityResponse(
        district=actual_district,
        state=actual_state,
        crop=crop_req.crop_name,
        assessment_date=date.today(),
        historical_rainfall=hist_stats,
        seasonal_outlook=outlook,
        crop_requirement=CropRequirementInfo(
            min_rainfall_mm=crop_req.min_rainfall_mm,
            optimal_rainfall_mm=crop_req.optimal_rainfall_mm,
            max_rainfall_mm=crop_req.max_rainfall_mm,
            growing_duration_days=crop_req.growing_duration_days,
            water_sensitivity=crop_req.water_sensitivity,
        ),
        verdict=verdict,
        surplus_deficit_mm=surplus_deficit,
        confidence=confidence,
        recommendation=recommendation,
    )
