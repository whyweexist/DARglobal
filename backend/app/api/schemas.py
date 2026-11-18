from typing import Literal
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=3, max_length=1500)
    model: str = Field(default="openrouter/free", max_length=150)
    source_filter: list[Literal["darglobal", "wasalt"]] = Field(default_factory=lambda: ["darglobal", "wasalt"], min_length=1, max_length=2)
    conversation_id: str | None = Field(default=None, max_length=64)
    conversation_token: str | None = Field(default=None, max_length=100)
    allow_live_search: bool = True
