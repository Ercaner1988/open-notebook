import asyncio
import time
import urllib.parse
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel, HttpUrl

from open_notebook.ai.connection_tester import test_individual_model
from open_notebook.ai.models import DefaultModels, Model
from open_notebook.database.repository import ensure_record_id, repo_delete, repo_query
from open_notebook.domain.credential import Credential
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


class ProviderConnectRequest(BaseModel):
    base_url: Optional[str] = None
    make_default: Optional[bool] = False
    confirm_dimension_mismatch: Optional[bool] = False


class ProviderConnectResponse(BaseModel):
    ok: bool
    credential_id: str
    model_id: str
    is_default: bool
    test_result: Dict[str, Any]
    message: Optional[str] = None


class ProviderDisconnectResponse(BaseModel):
    ok: bool
    message: str
    deleted_models: int


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
            parsed = urllib.parse.urlparse(item.base_url)
            path = parsed.path or "/v1"
            detected_url = f"http://127.0.0.1:{port}{path}"
            break

    _PROBE_CACHE[item.id] = (now, is_running, detected_url)
    return is_running, detected_url


def _normalize_id(record_id: Optional[str]) -> str:
    if not record_id:
        return ""
    return str(record_id)


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

    probe_results = await asyncio.gather(
        *[probe_item(item) for item in catalog], return_exceptions=True
    )

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


async def connect_provider(
    provider_id: str, request: ProviderConnectRequest
) -> ProviderConnectResponse:
    """
    Connect a provider according to Section 3.3 rules:
    1. Idempotent: reuse existing credential and model if matching.
    2. Do not overwrite default unless explicitly requested (make_default=True) or no default exists.
    3. Dimension check (409): reject if existing source embeddings have different dim and confirm_dimension_mismatch is False.
    4. SSRF protection on base_url.
    5. Test embedding after connection and return test result.
    """
    catalog = load_catalog()
    item = next((p for p in catalog if p.id == provider_id), None)
    if not item:
        raise HTTPException(
            status_code=404, detail=f"Provider '{provider_id}' not found in catalog"
        )

    target_base_url = request.base_url or item.base_url
    validate_connect_url(target_base_url, item)

    defaults = await DefaultModels.get_instance()
    current_default_id = getattr(defaults, "default_embedding_model", None)

    will_become_default = False
    if request.make_default:
        will_become_default = True
    elif not current_default_id:
        will_become_default = True

    # Rule 3: Dimension check
    if will_become_default:
        try:
            dim_rows = await repo_query(
                "SELECT array::len(embedding) AS dim FROM source_embedding LIMIT 1"
            )
            if dim_rows and isinstance(dim_rows, list) and len(dim_rows) > 0:
                first_row = dim_rows[0]
                existing_dim = first_row.get("dim")
                if (
                    existing_dim is not None
                    and existing_dim != item.dimension
                    and not request.confirm_dimension_mismatch
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Mevcut vektörler {existing_dim} boyutlu, bu sağlayıcı {item.dimension} boyutlu; "
                            "tüm kaynakları yeniden gömmeniz gerekir."
                        ),
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Could not check source_embedding dimensions: {e}")

    # Rule 1: Idempotent credential check
    credentials = await repo_query("SELECT * FROM credential")
    matching_cred_row = None
    target_clean = target_base_url.rstrip("/")
    for c in credentials:
        c_name = c.get("name")
        c_url = (c.get("base_url") or "").rstrip("/")
        if c_name == item.credential_name or (c_url and c_url == target_clean):
            matching_cred_row = c
            break

    if matching_cred_row:
        cred_id = str(matching_cred_row["id"])
        if (matching_cred_row.get("base_url") or "").rstrip("/") != target_clean:
            await repo_query(
                "UPDATE $cred_id SET base_url = $base_url",
                {"cred_id": ensure_record_id(cred_id), "base_url": target_base_url},
            )
    else:
        cred = Credential(
            name=item.credential_name,
            provider=item.provider_type,
            modalities=["embedding"],
            base_url=target_base_url,
        )
        await cred.save()
        cred_id = str(cred.id)

    # Rule 1: Idempotent model check
    existing_models = await repo_query(
        "SELECT * FROM model WHERE type = 'embedding' AND credential = $cred_id",
        {"cred_id": ensure_record_id(cred_id)},
    )
    matching_model_row = None
    for m in existing_models:
        if (m.get("name") or "").lower() == item.model.lower():
            matching_model_row = m
            break

    if matching_model_row:
        model_id = str(matching_model_row["id"])
        model = await Model.get(model_id)
    else:
        model = Model(
            name=item.model,
            provider=item.provider_type,
            type="embedding",
            credential=cred_id,
        )
        await model.save()
        model_id = str(model.id)

    # Rule 2: Update default embedding model if appropriate
    is_default = False
    if will_become_default:
        defaults.default_embedding_model = model_id
        await defaults.update()
        is_default = True
    else:
        is_default = bool(
            current_default_id
            and (
                str(current_default_id) == model_id
                or str(current_default_id).replace("model:", "")
                == model_id.replace("model:", "")
            )
        )

    # Rule 5: Test embedding
    try:
        test_ok, test_message = await test_individual_model(model)
    except Exception as e:
        test_ok = False
        test_message = str(e)[:200]

    return ProviderConnectResponse(
        ok=True,
        credential_id=cred_id,
        model_id=model_id,
        is_default=is_default,
        test_result={"ok": test_ok, "message": test_message},
        message=f"'{item.name}' başarıyla bağlandı.",
    )


async def disconnect_provider(provider_id: str) -> ProviderDisconnectResponse:
    """
    Disconnect a provider according to Rule 4:
    - Match credential using (base_url, name).
    - If model is current default_embedding_model, reject with 400.
    - Otherwise cascade-delete linked models and credential.
    """
    catalog = load_catalog()
    item = next((p for p in catalog if p.id == provider_id), None)
    if not item:
        raise HTTPException(
            status_code=404, detail=f"Provider '{provider_id}' not found in catalog"
        )

    credentials = await repo_query("SELECT * FROM credential")
    matching_cred_row = None
    for c in credentials:
        c_name = c.get("name")
        c_url = (c.get("base_url") or "").rstrip("/")
        if c_name == item.credential_name:
            parsed_c = urllib.parse.urlparse(c_url)
            is_url_match = (
                c_url == item.base_url.rstrip("/")
                or (
                    (parsed_c.hostname or "").lower() in ("127.0.0.1", "localhost")
                    and parsed_c.port in item.probe_ports
                )
            )
            if is_url_match:
                matching_cred_row = c
                break

    if not matching_cred_row:
        raise HTTPException(
            status_code=404,
            detail=f"'{item.name}' için kayıtlı bir bağlantı bulunamadı.",
        )

    cred_id = str(matching_cred_row["id"])
    linked_models = await repo_query(
        "SELECT * FROM model WHERE credential = $cred_id",
        {"cred_id": ensure_record_id(cred_id)},
    )
    linked_ids = {str(m.get("id")) for m in linked_models}

    defaults = await DefaultModels.get_instance()
    current_default = getattr(defaults, "default_embedding_model", None)
    current_default_str = str(current_default) if current_default else ""

    for mid in linked_ids:
        if mid == current_default_str or mid.replace("model:", "") == current_default_str.replace("model:", ""):
            raise HTTPException(
                status_code=400,
                detail="Bu sağlayıcının modeli şu anda varsayılan gömme modelidir. Bağlantıyı kaldırmadan önce başka bir varsayılan model seçin.",
            )

    deleted_models = 0
    for m in linked_models:
        m_id = str(m.get("id"))
        if m_id:
            await repo_delete(m_id)
            deleted_models += 1

    await repo_delete(cred_id)

    return ProviderDisconnectResponse(
        ok=True,
        message=f"'{item.name}' bağlantısı başarıyla kaldırıldı.",
        deleted_models=deleted_models,
    )
