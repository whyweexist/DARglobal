"""Server-side OpenRouter catalog with strict, verified zero-price model allowlist."""
from __future__ import annotations
import asyncio
import logging
import time
import httpx
from app.core.config import settings

log = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self):
        self._models: list[dict] = []
        self._last_fetch = 0.0
        self._lock = asyncio.Lock()
        self._catalog_reachable = False

    async def catalog(self, refresh: bool = False) -> list[dict]:
        if not refresh and self._last_fetch and time.monotonic() - self._last_fetch < settings().model_catalog_ttl_seconds:
            return self._models
        async with self._lock:
            if not refresh and self._last_fetch and time.monotonic() - self._last_fetch < settings().model_catalog_ttl_seconds:
                return self._models
            try:
                async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
                    response = await client.get(settings().openrouter_base_url.rstrip("/") + "/models")
                    response.raise_for_status()
                data = response.json().get("data", [])
                eligible = []
                for record in data:
                    price = record.get("pricing") or {}
                    if not self._free(price):
                        continue
                    model_id = record.get("id")
                    if not isinstance(model_id, str) or not model_id.endswith(":free"):
                        continue
                    modalities = record.get("architecture", {}).get("input_modalities", ["text"])
                    output_modalities = record.get("architecture", {}).get("output_modalities", ["text"])
                    if "text" not in modalities or "text" not in output_modalities:
                        continue
                    eligible.append({"id": model_id, "name": record.get("name") or model_id,
                                     "context_length": record.get("context_length"),
                                     "tools": "tools" in record.get("supported_parameters", []),
                                     "free": True})
                eligible.sort(key=lambda m: m["name"].casefold())
                self._models = eligible[:300]
                self._catalog_reachable = True
                self._last_fetch = time.monotonic()
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                log.warning("OpenRouter catalog unavailable: %s", type(exc).__name__)
                self._catalog_reachable = False
                self._last_fetch = time.monotonic() - settings().model_catalog_ttl_seconds + 60
            return self._models

    @staticmethod
    def _free(pricing: dict) -> bool:
        try:
            return all(key in pricing for key in ("prompt", "completion")) and all(
                float(pricing.get(key, "0")) == 0.0 for key in ("prompt", "completion", "request"))
        except (ValueError, TypeError):
            return False

    async def options(self, refresh: bool = False) -> dict:
        models = await self.catalog(refresh=refresh)
        return {"models": [{"id": "openrouter/free", "name": "Auto · Free router", "free": True,
                            "tools": False, "context_length": None}] + models,
                "catalog_online": self._catalog_reachable, "catalog_count": len(models), "configured": bool(settings().openrouter_api_key)}

    async def validate(self, value: str) -> None:
        if value == "openrouter/free":
            return
        models = await self.catalog()
        if value not in {m["id"] for m in models}:
            raise ValueError("Model is unavailable or not verified free in the current OpenRouter catalog")


registry = ModelRegistry()
