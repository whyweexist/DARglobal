"""Typed configuration. Never import credentials into client-side code."""
from functools import lru_cache
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_env: str = "development"
    database_url: str = "sqlite:////data/estate.db"
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    free_models_only: bool = True
    allowed_origins: str = "http://localhost:3000"
    app_domain: str = "localhost"
    api_rate_limit_per_minute: int = Field(default=12, ge=1, le=1000)
    scrape_on_boot: bool = True
    scraper_engine: Literal["httpx", "scrapling"] = "httpx"
    scrape_refresh_hours: int = Field(default=24, ge=1)
    crawl_max_pages: int = Field(default=15, ge=1, le=250)
    crawl_delay_seconds: float = Field(default=2, ge=0.5)
    darglobal_enabled: bool = True
    wasalt_authorized: bool = False
    wasalt_authorization_reference: str = ""
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = Field(default=384, ge=16)
    chunk_target_tokens: int = Field(default=400, ge=80, le=1200)
    chunk_max_tokens: int = Field(default=600, ge=120, le=1800)
    chunk_overlap_tokens: int = Field(default=60, ge=0, le=200)
    rag_max_context_chars: int = Field(default=12500, ge=1000, le=50000)
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    rag_live_search: bool = True
    agent_max_live_pages: int = Field(default=3, ge=0, le=15)
    agent_max_seconds: int = Field(default=22, ge=2, le=120)
    chat_deadline_seconds: int = Field(default=100, ge=15, le=240)
    llm_max_tokens: int = Field(default=1200, ge=100, le=4000)
    llm_timeout_seconds: int = Field(default=40, ge=5)
    model_catalog_ttl_seconds: int = Field(default=3600, ge=60)

    @property
    def cors_origins(self) -> list[str]:
        return [s.strip() for s in self.allowed_origins.split(",") if s.strip()]

    @property
    def wasalt_permitted(self) -> bool:
        return self.wasalt_authorized and bool(self.wasalt_authorization_reference.strip())


@lru_cache
def settings() -> Settings:
    return Settings()
