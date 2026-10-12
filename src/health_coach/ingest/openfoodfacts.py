"""Open Food Facts API client."""

import logging
from typing import Any

import httpx

from health_coach.config import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "health-coach/0.1 (self-hosted)"
DEFAULT_TIMEOUT = 5.0

_custom_client: httpx.Client | None = None


def set_client(client: httpx.Client | None) -> None:
    """Set or reset an injected httpx client (e.g. for testing with MockTransport)."""
    global _custom_client
    _custom_client = client


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return round(float(val), 1)
    except (ValueError, TypeError):
        return None


def parse_product(prod: dict[str, Any]) -> dict[str, Any]:
    nutriments = prod.get("nutriments") or {}
    serving = _to_float(prod.get("serving_quantity"))
    return {
        "id": None,
        "source": "openfoodfacts",
        "name": prod.get("product_name") or "Unknown product",
        "brand": prod.get("brands"),
        "barcode": prod.get("code"),
        "kcal_100g": _to_float(nutriments.get("energy-kcal_100g")),
        "protein_100g": _to_float(nutriments.get("proteins_100g")),
        "carbs_100g": _to_float(nutriments.get("carbohydrates_100g")),
        "fat_100g": _to_float(nutriments.get("fat_100g")),
        "fiber_100g": _to_float(nutriments.get("fiber_100g")),
        "default_serving_g": serving,
    }


class OpenFoodFactsClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or get_settings().off_base_url).rstrip("/")
        self.timeout = timeout
        self._injected_client = client

    def _get_client(self) -> httpx.Client:
        if self._injected_client is not None:
            return self._injected_client
        if _custom_client is not None:
            return _custom_client
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT},
        )

    def search_by_barcode(self, barcode: str) -> list[dict[str, Any]]:
        client = self._get_client()
        should_close = client is not self._injected_client and client is not _custom_client
        try:
            resp = client.get(f"{self.base_url}/api/v2/product/{barcode}.json")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            if not data.get("status") or "product" not in data:
                return []
            return [parse_product(data["product"])]
        finally:
            if should_close:
                client.close()

    def search_by_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        client = self._get_client()
        should_close = client is not self._injected_client and client is not _custom_client
        try:
            resp = client.get(
                f"{self.base_url}/cgi/search.pl",
                params={
                    "search_terms": query,
                    "json": 1,
                    "page_size": limit,
                    "fields": "code,product_name,brands,nutriments",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            products = data.get("products", [])
            return [parse_product(p) for p in products[:limit]]
        finally:
            if should_close:
                client.close()
