"""MCP server: read-only access to the CropCompass Postgres DB.

Schema source: scrapper/db/schema.sql + scrapper/db/rainfall_schema.sql

Tools exposed (read-only by design - no write methods):
  get_farmer_profile        - by farmer_id (UUID)
  fetch_latest_advisory     - latest IMD advisory for a district
  fetch_seasonal_outlook    - kharif/rabi/annual LRF for a district + year
  fetch_historical_rainfall - monthly rainfall window for a district
  get_crop_water_requirement- ICAR crop water profile
  list_districts            - district reference list (paged)
  fetch_district_summary    - aggregated rainfall summary view

Run:
  uvicorn mcp_servers.db_server.server:app --host 0.0.0.0 --port 9101
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import asyncpg
from fastapi import FastAPI

from agent_service.mcp_server_lib import MCPToolRegistry, mount_mcp

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://cropcompass:cropcompass_secret@localhost:5432/cropcompass",
).replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


registry = MCPToolRegistry()


@registry.tool(
    name="get_farmer_profile",
    description="Return farmer profile by UUID: district, state, soil, crop_variety, growth_stage, lang_pref, is_stale.",
    input_schema={
        "type": "object",
        "properties": {"farmer_id": {"type": "string", "description": "Farmer UUID."}},
        "required": ["farmer_id"],
    },
)
async def _get_farmer_profile(farmer_id: str) -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT farmer_id::text, name, phone, district, state, soil_type,
                   crop_variety, growth_stage, lang_pref, is_stale,
                   created_at, updated_at
              FROM farmers
             WHERE farmer_id = $1::uuid
            """,
            farmer_id,
        )
    if row is None:
        return {"error": f"farmer not found: {farmer_id}"}
    return {k: _jsonable(v) for k, v in dict(row).items()}


@registry.tool(
    name="fetch_latest_advisory",
    description="Most recent IMD GKMS advisory for a district (non-stale preferred).",
    input_schema={
        "type": "object",
        "properties": {"district": {"type": "string"}},
        "required": ["district"],
    },
)
async def _fetch_latest_advisory(district: str) -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT district, state, bulletin_date, rainfall_prob, rainfall_category,
                   min_temp_c, max_temp_c, humidity_pct, wind_speed_kmh, wind_direction,
                   season_outlook, advisory_text, source_url, fetched_at, is_stale
              FROM imd_advisories
             WHERE district ILIKE $1
             ORDER BY is_stale ASC, bulletin_date DESC, fetched_at DESC
             LIMIT 1
            """,
            district,
        )
    if row is None:
        return {"error": f"no advisory for district: {district}", "stale": True}
    return {k: _jsonable(v) for k, v in dict(row).items()}


@registry.tool(
    name="fetch_seasonal_outlook",
    description="IMD Long Range Forecast for a district, year, and season (kharif|rabi|annual).",
    input_schema={
        "type": "object",
        "properties": {
            "district": {"type": "string"},
            "forecast_year": {"type": "integer", "minimum": 1900, "maximum": 2100},
            "season": {"type": "string", "enum": ["kharif", "rabi", "annual"]},
        },
        "required": ["district", "forecast_year", "season"],
    },
)
async def _fetch_seasonal_outlook(district: str, forecast_year: int, season: str) -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT district, state, forecast_year, season, forecast_category,
                   prob_below_normal, prob_normal, prob_above_normal,
                   published_at, fetched_at, is_stale
              FROM imd_seasonal_outlook
             WHERE district ILIKE $1 AND forecast_year = $2 AND season = $3
             LIMIT 1
            """,
            district,
            forecast_year,
            season,
        )
    if row is None:
        return {"error": f"no outlook for {district} {forecast_year} {season}"}
    return {k: _jsonable(v) for k, v in dict(row).items()}


@registry.tool(
    name="fetch_historical_rainfall",
    description="Monthly historical rainfall rows for a district over an inclusive year range.",
    input_schema={
        "type": "object",
        "properties": {
            "district": {"type": "string"},
            "year_start": {"type": "integer", "minimum": 1900, "maximum": 2100},
            "year_end": {"type": "integer", "minimum": 1900, "maximum": 2100},
        },
        "required": ["district", "year_start", "year_end"],
    },
)
async def _fetch_historical_rainfall(district: str, year_start: int, year_end: int) -> dict[str, Any]:
    if year_end < year_start:
        return {"error": "year_end must be >= year_start"}
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT district, year, month, rainfall_mm, normal_rainfall_mm, departure_pct, is_stale
              FROM imd_historical_rainfall
             WHERE district ILIKE $1 AND year BETWEEN $2 AND $3
             ORDER BY year, month
            """,
            district,
            year_start,
            year_end,
        )
    return {"district": district, "rows": [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows]}


@registry.tool(
    name="get_crop_water_requirement",
    description="ICAR water profile for a crop: min/optimal/max rainfall, duration, season suitability.",
    input_schema={
        "type": "object",
        "properties": {"crop_name": {"type": "string"}},
        "required": ["crop_name"],
    },
)
async def _get_crop_water_requirement(crop_name: str) -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT crop_name, min_rainfall_mm, optimal_rainfall_mm, max_rainfall_mm,
                   growing_duration_days, kharif_suitable, rabi_suitable, zaid_suitable,
                   water_sensitivity, notes
              FROM crop_water_requirements
             WHERE crop_name ILIKE $1
            """,
            crop_name,
        )
    if row is None:
        return {"error": f"crop not found: {crop_name}"}
    return {k: _jsonable(v) for k, v in dict(row).items()}


@registry.tool(
    name="list_districts",
    description="Reference list of supported IMD districts, optionally filtered by state.",
    input_schema={
        "type": "object",
        "properties": {
            "state": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
    },
)
async def _list_districts(state: str | None = None, limit: int = 100) -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if state:
            rows = await conn.fetch(
                "SELECT district, state, latitude, longitude FROM imd_districts_ref WHERE is_active = TRUE AND state ILIKE $1 ORDER BY district LIMIT $2",
                state,
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT district, state, latitude, longitude FROM imd_districts_ref WHERE is_active = TRUE ORDER BY state, district LIMIT $1",
                limit,
            )
    return {"districts": [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows]}


@registry.tool(
    name="fetch_district_summary",
    description="Pre-aggregated rainfall summary per district: avg/min/max annual mm, monsoon avg, consistency score.",
    input_schema={
        "type": "object",
        "properties": {"district": {"type": "string"}},
        "required": ["district"],
    },
)
async def _fetch_district_summary(district: str) -> dict[str, Any]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM district_rainfall_summary WHERE district ILIKE $1",
            district,
        )
    if row is None:
        return {"error": f"no summary for district: {district}"}
    return {k: _jsonable(v) for k, v in dict(row).items()}


def _jsonable(v: Any) -> Any:
    if isinstance(v, (date,)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
        try:
            return float(v)
        except Exception:
            return str(v)
    return v


app = FastAPI(title="CropCompass DB MCP Server", version="0.1.0")
mount_mcp(app, registry)


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
