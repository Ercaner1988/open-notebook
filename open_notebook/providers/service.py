import asyncio
import time
import urllib.parse
from typing import Dict, List, Literal, Optional, Tuple

import httpx
from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel, HttpUrl

from open_notebook.ai.models import DefaultModels
from open_notebook.database.repository import repo_query
from open_notebook.providers import ProviderCatalogItem, ProviderDescription, load_catalog

# In-memory probe cache: { item_id: (timestamp, is_running, detected_url) }
_PROBE_CACHE: Dict[str, Tuple[float, bool, Optional[str]]] = {}
CACHE_TTL_SECONDS = 5.0


def clear_probe_cache() -> None:
    """Clear in-memory probe cache. Useful for testing."""
    _PROBE_CACHE.clear()


class ProviderStatusResponse(BaseModel):
    id: str
    name: str
    description: ProviderDescription
    homepage: Optional[HttpUrl] = None
    download_url: HttpUrl
    kind: str = "embedding"
    base_url: str
    probe_ports: List[int]
    health_path: str
    model: str
    dimension: int
    provider_type: str = "openai_compatible"
    credential_name: str
    notes: Optional[str] = None
    status: Literal["not_detected", "running", "connected", "default"]
    is_running: bool = False
    detected_url: Optional[str] = None
    connected_credential_id: Optional[str] = None
    connected_model_id: Optional[str] = None


async def probe_port(
    host: str, port: int, health_path: str, timeout: float = 1.5
) -> bool:
    """Probe a specific port on loopback with short timeout."""
    url = f"http://{host}:{port}{health_path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return resp.status_code < 400
    except Exception:
        return False


async def probe_item(
    item: ProviderCatalogItem,
) -> Tuple[bool, Optional[str]]:
    """
    Check if the provider server is running on any of its probe_ports.
    Uses a 5-second in-memory cache to avoid flooding local ports.
    """
    now = time.monotonic()
    if item.id in _PROBE_CACHE:
        cached_time, is_running, detected_url = _PROBE_CACHE[item.id]
        if now - cached_time < CACHE_TTL_SECONDS:
            return is_running, detected_url

    tasks = [
        probe_port("127.0.0.1", port, item.health_path) for port in item.probe_ports
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    is_running = False
    detected_url = None
    for port, res in zip(item.probe_ports, results):
        if res is True:
            is_running = True
            # Build detected URL using item.base_url path if present
            parsed = urllib.parse.urlparse(item.base_url)
            path = parsed.path or "/v1"
            detected_url = f"http://127.0.0.1:{port}{path}"
            break

    _PROBE_CACHE[item.id] = (now, is_running, detected_url)
    return is_running, detected_url


def _normalize_id(record_id: Optional[str]) -> str:
    if not record_id:
        return ""
    s = str(record_id)
    return s


def validate_connect_url(base_url: str, catalog_item: ProviderCatalogItem) -> None:
    """
    Validate base_url to prevent SSRF:
    Must be http/https, and host must either be loopback (127.0.0.1, localhost, ::1)
    or match catalog item's base_url host.
    """
    try:
        parsed = urllib.parse.urlparse(base_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base_url: {e}")

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="Invalid base_url: only http and https schemes are permitted",
        )

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid base_url: missing hostname")

    is_loopback = hostname in ("127.0.0.1", "localhost", "::1")

    catalog_parsed = urllib.parse.urlparse(catalog_item.base_url)
    catalog_hostname = (catalog_parsed.hostname or "").lower()
    is_catalog_host = bool(catalog_hostname and hostname == catalog_hostname)

    if not (is_loopback or is_catalog_host):
        raise HTTPException(
            status_code=400,
            detail="Invalid base_url: SSRF protection only allows loopback addresses or catalog URL",
        )


async def get_providers_with_status() -> List[ProviderStatusResponse]:
    """
    Load provider catalog and compute live status for each item:
    - not_detected: health check fails and not connected in DB
    - running: health check succeeds on loopback probe port, but not configured in DB
    - connected: credential + model exists in DB for this provider
    - default: model is the current default_embedding_model in Open Notebook
    """
    catalog = load_catalog()
    if not catalog:
        return []

    # Run loopback health probes in parallel
    probe_results = await asyncio.gather(
        *[probe_item(item) for item in catalog], return_exceptions=True
    )

    # Query DB for existing credentials, models, and default models
    try:
        credentials = await repo_query("SELECT * FROM credential")
    except Exception as e:
        logger.error(f"Error querying credentials for provider store: {e}")
        credentials = []

    try:
        models = await repo_query("SELECT * FROM model WHERE type = 'embedding'")
    except Exception as e:
        logger.error(f"Error querying models for provider store: {e}")
        models = []

    try:
        defaults = await DefaultModels.get_instance()
        default_embedding_id = getattr(defaults, "default_embedding_model", None)
    except Exception as e:
        logger.error(f"Error getting default models: {e}")
        default_embedding_id = None

    default_embedding_str = _normalize_id(default_embedding_id)

    response_items: List[ProviderStatusResponse] = []

    for item, p_res in zip(catalog, probe_results):
        if isinstance(p_res, tuple):
            is_running, detected_url = p_res
        else:
            is_running, detected_url = False, None

        # Find matching credential
        matching_cred = None
        for cred in credentials:
            c_name = cred.get("name")
            c_url = (cred.get("base_url") or "").rstrip("/")
            item_url = item.base_url.rstrip("/")

            name_match = (c_name == item.credential_name)
            url_match = False
            if c_url:
                if c_url == item_url:
                    url_match = True
                else:
                    # Check loopback match on probe ports
                    parsed_c = urllib.parse.urlparse(c_url)
                    if (parsed_c.hostname or "").lower() in ("127.0.0.1", "localhost") and parsed_c.port in item.probe_ports:
                        url_match = True

            if name_match or url_match:
                matching_cred = cred
                break

        matching_model = None
        if matching_cred:
            cred_id_str = _normalize_id(matching_cred.get("id"))
            for m in models:
                m_cred_str = _normalize_id(m.get("credential"))
                m_name = (m.get("name") or "").lower()
                if (m_cred_str == cred_id_str or m_cred_str.replace("credential:", "") == cred_id_str.replace("credential:", "")) and (
                    m_name == item.model.lower() or not item.model
                ):
                    matching_model = m
                    break

        connected_cred_id = _normalize_id(matching_cred.get("id")) if matching_cred else None
        connected_model_id = _normalize_id(matching_model.get("id")) if matching_model else None

        # Calculate status
        if matching_cred and matching_model:
            if default_embedding_str and (
                default_embedding_str == connected_model_id
                or default_embedding_str.replace("model:", "") == (connected_model_id or "").replace("model:", "")
            ):
                status: Literal["not_detected", "running", "connected", "default"] = "default"
            else:
                status = "connected"
        elif is_running:
            status = "running"
        else:
            status = "not_detected"

        response_items.append(
            ProviderStatusResponse(
                id=item.id,
                name=item.name,
                description=item.description,
                homepage=item.homepage,
                download_url=item.download_url,
                kind=item.kind,
                base_url=detected_url or item.base_url,
                probe_ports=item.probe_ports,
                health_path=item.health_path,
                model=item.model,
                dimension=item.dimension,
                provider_type=item.provider_type,
                credential_name=item.credential_name,
                notes=item.notes,
                status=status,
                is_running=is_running,
                detected_url=detected_url,
                connected_credential_id=connected_cred_id,
                connected_model_id=connected_model_id,
            )
        )

    return response_items
