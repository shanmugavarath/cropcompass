import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

SoilType    = Literal["loamy", "clay", "sandy", "black", "red", "alluvial", "laterite"]
CropVariety = Literal["rice", "wheat", "maize", "cotton", "soybean", "sugarcane", "pulses", "vegetables"]
GrowthStage = Literal["sowing", "germination", "vegetative", "flowering", "fruiting", "harvesting"]
LangPref    = Literal["hin_Deva", "tam_Taml", "tel_Telu", "mar_Deva", "pan_Guru", "eng_Latn"]

SUPPORTED_LANGS: list[str] = ["hin_Deva", "tam_Taml", "tel_Telu", "mar_Deva", "pan_Guru", "eng_Latn"]


class FarmerCreate(BaseModel):
    district:     str                  = Field(..., min_length=2, max_length=100, examples=["Chennai"])
    state:        str                  = Field(..., min_length=2, max_length=100, examples=["Tamil Nadu"])
    name:         str | None           = Field(None, max_length=200)
    phone:        str | None           = Field(None, max_length=20)
    soil_type:    SoilType | None      = None
    crop_variety: CropVariety | None   = None
    growth_stage: GrowthStage | None   = None
    lang_pref:    LangPref             = "eng_Latn"


class FarmerUpdate(BaseModel):
    name:         str | None           = Field(None, max_length=200)
    phone:        str | None           = Field(None, max_length=20)
    district:     str | None           = Field(None, min_length=2, max_length=100)
    state:        str | None           = Field(None, min_length=2, max_length=100)
    soil_type:    SoilType | None      = None
    crop_variety: CropVariety | None   = None
    growth_stage: GrowthStage | None   = None
    lang_pref:    LangPref | None      = None


class FarmerResponse(BaseModel):
    model_config = {"from_attributes": True}

    farmer_id:    uuid.UUID
    district:     str
    state:        str
    name:         str | None
    phone:        str | None
    soil_type:    str | None
    crop_variety: str | None
    growth_stage: str | None
    lang_pref:    str
    created_at:   datetime
    updated_at:   datetime
    is_stale:     bool
