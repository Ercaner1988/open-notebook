from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from open_notebook.providers.service import clear_probe_cache


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_probe_cache()
    yield
    clear_probe_cache()


def test_get_providers_registry_endpoint(client):
    """GET /api/providers/registry returns the AI provider registry metadata."""
    response = client.get("/api/providers/registry")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(item["name"] == "openai" for item in data)
    assert any(item["name"] == "anthropic" for item in data)


def test_get_providers_backward_compat_format_registry(client):
    """GET /api/providers?format=registry returns the AI provider registry metadata."""
    response = client.get("/api/providers?format=registry")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(item["name"] == "openai" for item in data)


@pytest.mark.asyncio
async def test_get_providers_not_detected(client):
    """When server does not respond and no DB record exists -> not_detected."""
    fake_repo = AsyncMock(return_value=[])
    fake_defaults = type("D", (), {"default_embedding_model": None})()

    with (
        patch("open_notebook.providers.service.probe_port", AsyncMock(return_value=False)),
        patch("open_notebook.providers.service.repo_query", fake_repo),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=fake_defaults)),
    ):
        response = client.get("/api/providers")

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    bge = next((p for p in data if p["id"] == "bge-embed-rs"), None)
    assert bge is not None
    assert bge["status"] == "not_detected"
    assert bge["is_running"] is False


@pytest.mark.asyncio
async def test_get_providers_running(client):
    """When server responds to health check but not in DB -> running."""
    fake_repo = AsyncMock(return_value=[])
    fake_defaults = type("D", (), {"default_embedding_model": None})()

    async def fake_probe(host, port, path, timeout=1.5):
        return port == 11434

    with (
        patch("open_notebook.providers.service.probe_port", side_effect=fake_probe),
        patch("open_notebook.providers.service.repo_query", fake_repo),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=fake_defaults)),
    ):
        response = client.get("/api/providers")

    assert response.status_code == 200
    data = response.json()
    bge = next((p for p in data if p["id"] == "bge-embed-rs"), None)
    assert bge is not None
    assert bge["status"] == "running"
    assert bge["is_running"] is True
    assert "11434" in (bge["detected_url"] or "")


@pytest.mark.asyncio
async def test_get_providers_connected(client):
    """When credential + model exists in DB, but not default -> connected."""
    fake_credentials = [
        {
            "id": "credential:bge1",
            "name": "bge-embed-rs",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:11434/v1",
        }
    ]
    fake_models = [
        {
            "id": "model:m_bge",
            "name": "bge-m3",
            "provider": "openai_compatible",
            "type": "embedding",
            "credential": "credential:bge1",
        }
    ]

    async def fake_repo(query, vars=None):
        if "FROM credential" in query:
            return fake_credentials
        if "FROM model" in query:
            return fake_models
        return []

    fake_defaults = type("D", (), {"default_embedding_model": "model:other_model"})()

    with (
        patch("open_notebook.providers.service.probe_port", AsyncMock(return_value=True)),
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=fake_defaults)),
    ):
        response = client.get("/api/providers")

    assert response.status_code == 200
    data = response.json()
    bge = next((p for p in data if p["id"] == "bge-embed-rs"), None)
    assert bge is not None
    assert bge["status"] == "connected"
    assert bge["connected_credential_id"] == "credential:bge1"
    assert bge["connected_model_id"] == "model:m_bge"


@pytest.mark.asyncio
async def test_get_providers_default(client):
    """When credential + model exists in DB and is default_embedding_model -> default."""
    fake_credentials = [
        {
            "id": "credential:bge1",
            "name": "bge-embed-rs",
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:11434/v1",
        }
    ]
    fake_models = [
        {
            "id": "model:m_bge",
            "name": "bge-m3",
            "provider": "openai_compatible",
            "type": "embedding",
            "credential": "credential:bge1",
        }
    ]

    async def fake_repo(query, vars=None):
        if "FROM credential" in query:
            return fake_credentials
        if "FROM model" in query:
            return fake_models
        return []

    fake_defaults = type("D", (), {"default_embedding_model": "model:m_bge"})()

    with (
        patch("open_notebook.providers.service.probe_port", AsyncMock(return_value=True)),
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=fake_defaults)),
    ):
        response = client.get("/api/providers")

    assert response.status_code == 200
    data = response.json()
    bge = next((p for p in data if p["id"] == "bge-embed-rs"), None)
    assert bge is not None
    assert bge["status"] == "default"
    assert bge["connected_credential_id"] == "credential:bge1"
    assert bge["connected_model_id"] == "model:m_bge"


@pytest.mark.asyncio
async def test_probe_cache_prevents_duplicate_calls(client):
    """Consecutive calls within TTL reuse cached probe result."""
    fake_repo = AsyncMock(return_value=[])
    fake_defaults = type("D", (), {"default_embedding_model": None})()
    probe_mock = AsyncMock(return_value=True)

    with (
        patch("open_notebook.providers.service.probe_port", probe_mock),
        patch("open_notebook.providers.service.repo_query", fake_repo),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=fake_defaults)),
    ):
        resp1 = client.get("/api/providers")
        assert resp1.status_code == 200
        call_count_1 = probe_mock.call_count

        # Second call immediately after should use probe cache
        resp2 = client.get("/api/providers")
        assert resp2.status_code == 200
        assert probe_mock.call_count == call_count_1
