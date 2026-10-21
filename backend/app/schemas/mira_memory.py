from typing import Literal
from pydantic import BaseModel, Field


class MemoryEdit(BaseModel):
    version: int
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=4000)


class MemoryStatusChange(BaseModel):
    version: int
    action: Literal['close', 'reopen', 'wrong']
