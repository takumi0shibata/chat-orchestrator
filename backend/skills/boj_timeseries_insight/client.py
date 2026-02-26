from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

API_BASE = "https://www.stat-search.boj.or.jp"


@dataclass
class BojApiError(Exception):
    endpoint: str
    status: str
    message: str

    def __str__(self) -> str:
        return f"{self.endpoint}: status={self.status}, message={self.message}"


class BojStatClient:
    def __init__(self, *, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get_metadata(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = await self._get_json("api/v1/getMetadata", params)
        self._validate_result(endpoint="api/v1/getMetadata", payload=payload)
        return payload

    async def get_data_code(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = await self._get_json("api/v1/getDataCode", params)
        self._validate_result(endpoint="api/v1/getDataCode", payload=payload)
        return payload

    async def _get_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.get(
            f"{API_BASE}/{endpoint}",
            params=params,
        )
        if response.status_code != 200:
            raise BojApiError(endpoint=endpoint, status=str(response.status_code), message="HTTP error")
        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover
            raise BojApiError(endpoint=endpoint, status="invalid_json", message=str(exc)) from exc
        if not isinstance(payload, dict):
            raise BojApiError(endpoint=endpoint, status="unexpected_payload", message="Expected object")
        return payload

    def _validate_result(self, *, endpoint: str, payload: dict[str, Any]) -> None:
        result = payload.get("RESULT")
        status = ""
        message = ""
        if isinstance(result, dict):
            status = str(result.get("STATUS") or result.get("status") or "")
            message = str(result.get("ERROR_MSG") or result.get("MESSAGE") or "")
        elif isinstance(result, str):
            status = result
        if status and status not in {"0", "00", "success", "SUCCESS"}:
            raise BojApiError(endpoint=endpoint, status=status, message=message or "API returned error status")
