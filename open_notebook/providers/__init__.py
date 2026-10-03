import json
from importlib import resources
from pathlib import Path
from typing import List, Literal, Optional

from loguru import logger
from pydantic import BaseModel, HttpUrl, field_validator


class ProviderDescription(BaseModel):
    en: str
    tr: str


class ProviderCatalogItem(BaseModel):
    id: str
    name: str
    description: ProviderDescription
    homepage: Optional[HttpUrl] = None
    download_url: HttpUrl
    kind: Literal["embedding"] = "embedding"
    base_url: str
    probe_ports: List[int]
    health_path: str
    model: str
    dimension: int
    provider_type: str = "openai_compatible"
    credential_name: str
    notes: Optional[str] = None

    @field_validator("download_url")
    @classmethod
    def validate_download_url_https(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme != "https":
            raise ValueError("download_url must be https")
        return v

    @field_validator("probe_ports")
    @classmethod
    def validate_ports(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("probe_ports cannot be empty")
        for port in v:
            if not (1 <= port <= 65535):
                raise ValueError(f"Invalid port: {port}")
        return v


def load_catalog(catalog_path: Optional[Path] = None) -> List[ProviderCatalogItem]:
    """
    Loads and validates provider entries from catalog.json.
    Corrupted or invalid records are logged and skipped rather than dropping the whole list.
    """
    raw_text: Optional[str] = None
    if catalog_path and catalog_path.exists():
        raw_text = catalog_path.read_text(encoding="utf-8")
    else:
        try:
            # Package resource access
            raw_text = (
                resources.files("open_notebook.providers")
                .joinpath("catalog.json")
                .read_text(encoding="utf-8")
            )
        except Exception as e:
            logger.warning(f"Could not load catalog via importlib.resources: {e}")
            fallback_file = Path(__file__).parent / "catalog.json"
            if fallback_file.exists():
                raw_text = fallback_file.read_text(encoding="utf-8")

    if not raw_text:
        logger.error("Provider catalog.json could not be loaded from any source")
        return []

    try:
        raw_entries = json.loads(raw_text)
    except Exception as e:
        logger.error(f"Failed to parse provider catalog JSON: {e}")
        return []

    if not isinstance(raw_entries, list):
        logger.error("Provider catalog format invalid: expected a list of objects")
        return []

    valid_items: List[ProviderCatalogItem] = []
    for idx, entry in enumerate(raw_entries):
        try:
            item = ProviderCatalogItem.model_validate(entry)
            valid_items.append(item)
        except Exception as e:
            item_id = entry.get("id", f"index-{idx}") if isinstance(entry, dict) else f"index-{idx}"
            logger.warning(f"Skipping invalid provider catalog entry '{item_id}': {e}")

    return valid_items


__all__ = [
    "ProviderDescription",
    "ProviderCatalogItem",
    "load_catalog",
]
