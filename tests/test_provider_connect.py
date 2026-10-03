from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ----------------------------------------------------------------------
# Rule 1 & Critical Scenario:
# Varsayılan zaten 11434'teki bge-m3; 11435'ten connect ->
# varsayılan değişmez, ikinci credential açılmaz.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critical_scenario_connect_from_different_port_does_not_clobber_default_or_dupe_cred(client):
    """
    CRITICAL SCENARIO:
    Default is already bge-m3 at 11434.
    Connect from 11435 without make_default=True:
    - Default must NOT change.
    - No duplicate credential or model created.
    """
    existing_cred = {
        "id": "credential:bge_existing",
        "name": "bge-embed-rs",
        "provider": "openai_compatible",
        "base_url": "http://127.0.0.1:11434/v1",
    }
    existing_model = {
        "id": "model:bge_m3_model",
        "name": "bge-m3",
        "provider": "openai_compatible",
        "type": "embedding",
        "credential": "credential:bge_existing",
    }

    credentials = [dict(existing_cred)]
    models = [dict(existing_model)]
    defaults = type("D", (), {"default_embedding_model": "model:bge_m3_model", "update": AsyncMock()})()

    query_calls = []

    async def fake_repo_query(query, vars=None):
        query_calls.append((query, vars))
        if "FROM credential" in query:
            return credentials
        if "FROM model" in query:
            return models
        if "UPDATE $cred_id SET base_url" in query:
            for c in credentials:
                if str(c["id"]) == str(vars.get("cred_id")):
                    c["base_url"] = vars.get("base_url")
            return []
        return []

    with (
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo_query),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=defaults)),
        patch("open_notebook.providers.service.test_individual_model", AsyncMock(return_value=(True, "Dimensions: 1024"))),
        patch("open_notebook.domain.credential.Credential.save", AsyncMock()),
        patch("open_notebook.ai.models.Model.save", AsyncMock()),
        patch("open_notebook.ai.models.Model.get", AsyncMock(return_value=existing_model)),
    ):
        response = client.post(
            "/api/providers/bge-embed-rs/connect",
            json={"base_url": "http://127.0.0.1:11435/v1", "make_default": False},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    # Reused existing credential and model
    assert data["credential_id"] == "credential:bge_existing"
    assert data["model_id"] == "model:bge_m3_model"
    # Default did NOT change (remains the existing default)
    assert defaults.default_embedding_model == "model:bge_m3_model"
    defaults.update.assert_not_called()
    assert data["test_result"]["ok"] is True


# ----------------------------------------------------------------------
# Rule 2: Auto-assign default if no default existed
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_auto_assigns_default_when_no_default_exists(client):
    """When no default embedding model is set, connecting a provider assigns it as default."""
    credentials = []
    models = []
    defaults = type("D", (), {"default_embedding_model": None, "update": AsyncMock()})()

    async def fake_repo_query(query, vars=None):
        if "FROM credential" in query:
            return credentials
        if "FROM model" in query:
            return models
        if "FROM source_embedding" in query:
            return []
        return []

    async def fake_cred_save(self, *args, **kwargs):
        self.id = "credential:new_cred"
        return self

    async def fake_model_save(self, *args, **kwargs):
        self.id = "model:new_model"
        return self

    with (
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo_query),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=defaults)),
        patch("open_notebook.providers.service.test_individual_model", AsyncMock(return_value=(True, "Embedding successful"))),
        patch("open_notebook.domain.credential.Credential.save", fake_cred_save),
        patch("open_notebook.ai.models.Model.save", fake_model_save),
    ):
        response = client.post(
            "/api/providers/bge-embed-rs/connect",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["is_default"] is True
    assert defaults.default_embedding_model == "model:new_model"
    defaults.update.assert_called_once()


# ----------------------------------------------------------------------
# Rule 3: Dimension check (409 Conflict)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_dimension_mismatch_returns_409(client):
    """
    If existing source embeddings have different dimension and make_default=True,
    reject with 409 unless confirm_dimension_mismatch=True.
    """
    defaults = type("D", (), {"default_embedding_model": "model:old_gemini", "update": AsyncMock()})()

    async def fake_repo_query(query, vars=None):
        if "FROM source_embedding" in query:
            return [{"dim": 3072}]
        return []

    with (
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo_query),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=defaults)),
    ):
        response = client.post(
            "/api/providers/bge-embed-rs/connect",
            json={"make_default": True, "confirm_dimension_mismatch": False},
        )

    assert response.status_code == 409
    assert "3072" in response.json()["detail"]
    assert "1024" in response.json()["detail"]


@pytest.mark.asyncio
async def test_connect_dimension_mismatch_proceeds_with_confirm_flag(client):
    """With confirm_dimension_mismatch=True, 409 is bypassed and default is updated."""
    defaults = type("D", (), {"default_embedding_model": "model:old_gemini", "update": AsyncMock()})()
    credentials = []
    models = []

    async def fake_repo_query(query, vars=None):
        if "FROM source_embedding" in query:
            return [{"dim": 3072}]
        if "FROM credential" in query:
            return credentials
        if "FROM model" in query:
            return models
        return []

    async def fake_cred_save(self, *args, **kwargs):
        self.id = "credential:new_bge"
        return self

    async def fake_model_save(self, *args, **kwargs):
        self.id = "model:new_bge_m3"
        return self

    with (
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo_query),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=defaults)),
        patch("open_notebook.providers.service.test_individual_model", AsyncMock(return_value=(True, "Embedding dimensions: 1024"))),
        patch("open_notebook.domain.credential.Credential.save", fake_cred_save),
        patch("open_notebook.ai.models.Model.save", fake_model_save),
    ):
        response = client.post(
            "/api/providers/bge-embed-rs/connect",
            json={"make_default": True, "confirm_dimension_mismatch": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["is_default"] is True
    assert defaults.default_embedding_model == "model:new_bge_m3"


# ----------------------------------------------------------------------
# Rule 4: Disconnect safety
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_rejects_if_model_is_default(client):
    """If provider's model is currently default_embedding_model, disconnect must return 400."""
    matching_cred = {
        "id": "credential:bge1",
        "name": "bge-embed-rs",
        "base_url": "http://127.0.0.1:11435/v1",
    }
    linked_models = [
        {"id": "model:bge_m3", "name": "bge-m3", "credential": "credential:bge1"}
    ]
    defaults = type("D", (), {"default_embedding_model": "model:bge_m3"})()

    async def fake_repo_query(query, vars=None):
        if "FROM credential" in query:
            return [matching_cred]
        if "FROM model" in query:
            return linked_models
        return []

    with (
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo_query),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=defaults)),
    ):
        response = client.post("/api/providers/bge-embed-rs/disconnect")

    assert response.status_code == 400
    assert "varsayılan" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_disconnect_deletes_credential_and_models_when_not_default(client):
    """When not default, disconnect cascade-deletes linked models and the credential."""
    matching_cred = {
        "id": "credential:bge1",
        "name": "bge-embed-rs",
        "base_url": "http://127.0.0.1:11435/v1",
    }
    linked_models = [
        {"id": "model:bge_m3", "name": "bge-m3", "credential": "credential:bge1"}
    ]
    defaults = type("D", (), {"default_embedding_model": "model:some_other_model"})()

    deleted_records = []

    async def fake_repo_query(query, vars=None):
        if "FROM credential" in query:
            return [matching_cred]
        if "FROM model" in query:
            return linked_models
        return []

    async def fake_repo_delete(record_id):
        deleted_records.append(str(record_id))

    with (
        patch("open_notebook.providers.service.repo_query", side_effect=fake_repo_query),
        patch("open_notebook.providers.service.DefaultModels.get_instance", AsyncMock(return_value=defaults)),
        patch("open_notebook.providers.service.repo_delete", side_effect=fake_repo_delete),
    ):
        response = client.post("/api/providers/bge-embed-rs/disconnect")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["deleted_models"] == 1
    assert "model:bge_m3" in deleted_records
    assert "credential:bge1" in deleted_records


# ----------------------------------------------------------------------
# SSRF Protection
# ----------------------------------------------------------------------


def test_connect_ssrf_protection_rejects_arbitrary_urls(client):
    """Connecting with arbitrary external/internal IPs must be rejected with 400."""
    bad_urls = [
        "http://192.168.1.50:8000/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://evil.com/v1",
        "ftp://127.0.0.1:11435/v1",
    ]
    for url in bad_urls:
        response = client.post(
            "/api/providers/bge-embed-rs/connect",
            json={"base_url": url},
        )
        assert response.status_code == 400
        assert "SSRF" in response.json()["detail"] or "scheme" in response.json()["detail"]
