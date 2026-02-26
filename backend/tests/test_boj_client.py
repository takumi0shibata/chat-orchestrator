import asyncio

import httpx
import pytest

from skills.boj_timeseries_insight.client import BojApiError, BojStatClient


def test_client_success_with_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/getDataCode"
        if request.url.path.endswith("/api/v1/getDataCode"):
            return httpx.Response(200, json={"RESULT": {"STATUS": 0}, "DATA": []})
        return httpx.Response(404, json={})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            api = BojStatClient(client=client)
            data_payload = await api.get_data_code({"db": "PR01", "code": "PRCG20_2200000000"})
            assert data_payload["RESULT"]["STATUS"] == 0

    asyncio.run(run())


def test_client_raises_for_api_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"RESULT": {"STATUS": 1, "ERROR_MSG": "bad request"}})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            api = BojStatClient(client=client)
            with pytest.raises(BojApiError):
                await api.get_data_code({"db": "PR01", "code": "PRCG20_2200000000"})

    asyncio.run(run())
