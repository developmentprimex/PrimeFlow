import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class DesktopStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: uuid.UUID
    title: str = Field(min_length=1, max_length=200, pattern=r'\S')
    consent_acknowledged: Literal[True]


class DesktopFinish(BaseModel):
    model_config = ConfigDict(extra='forbid')
    segment_count: int = Field(ge=0, le=14400, strict=True)
    partial: bool = False
