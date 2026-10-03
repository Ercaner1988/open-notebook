import json
import pytest
from pydantic import ValidationError

from open_notebook.providers import ProviderCatalogItem, load_catalog


def test_load_default_catalog():
    items = load_catalog()
    assert len(items) >= 1
    bge = next((it for it in items if it.id == "bge-embed-rs"), None)
    assert bge is not None
    assert bge.name == "bge-embed-rs"
    assert bge.dimension == 1024
    assert str(bge.download_url).startswith("https://")
    assert 11434 in bge.probe_ports or 11435 in bge.probe_ports


def test_invalid_download_url_http_rejected():
    with pytest.raises(ValidationError):
        ProviderCatalogItem.model_validate(
            {
                "id": "bad-url",
                "name": "Bad URL",
                "description": {"en": "Bad", "tr": "Kötü"},
                "download_url": "http://insecure.com/download",
                "kind": "embedding",
                "base_url": "http://127.0.0.1:11434/v1",
                "probe_ports": [11434],
                "health_path": "/health",
                "model": "bge-m3",
                "dimension": 1024,
                "provider_type": "openai_compatible",
                "credential_name": "bad",
            }
        )


def test_corrupted_record_skipped_gracefully(tmp_path):
    catalog_content = [
        {
            "id": "valid-1",
            "name": "Valid 1",
            "description": {"en": "Valid", "tr": "Geçerli"},
            "download_url": "https://example.com/download",
            "kind": "embedding",
            "base_url": "http://127.0.0.1:11434/v1",
            "probe_ports": [11434],
            "health_path": "/health",
            "model": "bge-m3",
            "dimension": 1024,
            "provider_type": "openai_compatible",
            "credential_name": "valid-1",
        },
        {
            "id": "broken-item",
            "name": "Missing required fields",
            # missing description, download_url, etc.
        },
        {
            "id": "valid-2",
            "name": "Valid 2",
            "description": {"en": "Valid 2", "tr": "Geçerli 2"},
            "download_url": "https://example.com/download2",
            "kind": "embedding",
            "base_url": "http://127.0.0.1:1234/v1",
            "probe_ports": [1234],
            "health_path": "/health",
            "model": "bge-m3",
            "dimension": 1024,
            "provider_type": "openai_compatible",
            "credential_name": "valid-2",
        },
    ]
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(json.dumps(catalog_content), encoding="utf-8")

    items = load_catalog(catalog_file)
    assert len(items) == 2
    assert items[0].id == "valid-1"
    assert items[1].id == "valid-2"


def test_empty_or_malformed_json(tmp_path):
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text("not json at all", encoding="utf-8")
    assert load_catalog(catalog_file) == []

    catalog_file.write_text('{"not": "a list"}', encoding="utf-8")
    assert load_catalog(catalog_file) == []
