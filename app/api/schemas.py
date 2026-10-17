from typing import Literal

from pydantic import BaseModel, Field


class LogSourceCreate(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=240)


class AnalysisRequest(BaseModel):
    provider: Literal["local", "openai", "anthropic"] | None = None

