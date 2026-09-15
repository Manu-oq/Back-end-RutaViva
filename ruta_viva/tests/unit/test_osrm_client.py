from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.osrm_client import OSRMClient, get_osrm_client, reset_osrm_client


class TestOSRMClientInit:
    def test_default_base_url(self) -> None:
        client = OSRMClient()
        assert client._base_url == "http://rutaviva_osrm:5000"

    def test_custom_base_url(self) -> None:
        client = OSRMClient(base_url="http://osrm:6000")
        assert client._base_url == "http://osrm:6000"

    def test_trailing_slash_removed(self) -> None:
        client = OSRMClient(base_url="http://localhost:5000/")
        assert client._base_url == "http://localhost:5000"


class TestGetRoute:
    @pytest.mark.asyncio
    async def test_returns_duration_and_distance(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [{"duration": 4680.2, "distance": 102348.5}],
        }
        client._http_client.get = AsyncMock(return_value=mock_response)

        result = await client.get_route(-38.9, -72.667, -39.282, -71.977, profile="driving")
        assert result["duration_seconds"] == 4680.2
        assert result["distance_meters"] == 102348.5

    @pytest.mark.asyncio
    async def test_fallback_on_http_error(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        client._http_client.get = AsyncMock(side_effect=OSError("connection refused"))

        result = await client.get_route(-38.9, -72.667, -39.282, -71.977, profile="driving")
        assert result["duration_seconds"] > 0
        assert result["distance_meters"] > 0

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_response(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"code": "NoRoute", "routes": []}
        client._http_client.get = AsyncMock(return_value=mock_response)

        result = await client.get_route(-38.9, -72.667, -39.282, -71.977, profile="driving")
        assert result["duration_seconds"] > 0

    @pytest.mark.asyncio
    async def test_invalid_profile_raises(self) -> None:
        client = OSRMClient()
        with pytest.raises(ValueError, match="Perfil no soportado"):
            await client.get_route(0, 0, 0, 0, profile="bicycle")

    @pytest.mark.asyncio
    async def test_foot_profile(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [{"duration": 7200, "distance": 15000}],
        }
        client._http_client.get = AsyncMock(return_value=mock_response)

        result = await client.get_route(0, 0, 1, 1, profile="foot")
        assert result["duration_seconds"] == 7200
        assert result["distance_meters"] == 15000

    @pytest.mark.asyncio
    async def test_haversine_fallback_calculates_correctly(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        client._http_client.get = AsyncMock(side_effect=OSError())

        result = await client.get_route(0, 0, 0, 1, profile="driving")
        mt = 111195.0
        expected_seconds = (mt / 1000.0) / 40.0 * 3600.0
        assert abs(result["duration_seconds"] - expected_seconds) < 10
        assert abs(result["distance_meters"] - mt) < 1000

    @pytest.mark.asyncio
    async def test_foot_fallback_speed(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        client._http_client.get = AsyncMock(side_effect=OSError())

        result = await client.get_route(0, 0, 0, 1, profile="foot")
        driving_result = await client.get_route(0, 0, 0, 1, profile="driving")
        assert result["duration_seconds"] > driving_result["duration_seconds"]

    @pytest.mark.asyncio
    async def test_same_point_zero_distance(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [{"duration": 0, "distance": 0}],
        }
        client._http_client.get = AsyncMock(return_value=mock_response)

        result = await client.get_route(-38.9, -72.667, -38.9, -72.667)
        assert result["duration_seconds"] == 0
        assert result["distance_meters"] == 0


class TestGetTable:
    @pytest.mark.asyncio
    async def test_returns_matrix(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "durations": [[4680.2, 0.0]],
            "distances": [[102348.5, 0.0]],
        }
        client._http_client.get = AsyncMock(return_value=mock_response)

        sources = [(-38.9, -72.667)]
        destinations = [(-39.282, -71.977), (-38.9, -72.667)]
        result = await client.get_table(sources, destinations, profile="driving")

        assert result is not None
        assert len(result) == 1
        assert result[0][0]["duration_seconds"] == 4680.2
        assert result[0][1]["duration_seconds"] == 0.0

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        client._http_client.get = AsyncMock(side_effect=OSError())

        result = await client.get_table([(0, 0)], [(1, 1)])
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_profile_raises(self) -> None:
        client = OSRMClient()
        with pytest.raises(ValueError, match="Perfil no soportado"):
            await client.get_table([(0, 0)], [(1, 1)], profile="bicycle")

    @pytest.mark.asyncio
    async def test_returns_none_on_no_route(self) -> None:
        client = OSRMClient(base_url="http://fake-osrm")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"code": "NoTable", "durations": None}
        client._http_client.get = AsyncMock(return_value=mock_response)

        result = await client.get_table([(0, 0)], [(1, 1)])
        assert result is None


class TestSingleton:
    def test_get_osrm_client_returns_same_instance(self) -> None:
        reset_osrm_client()
        c1 = get_osrm_client()
        c2 = get_osrm_client()
        assert c1 is c2

    def test_reset_osrm_client(self) -> None:
        c1 = get_osrm_client()
        reset_osrm_client()
        c2 = get_osrm_client()
        assert c1 is not c2
