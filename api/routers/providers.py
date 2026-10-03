"""
Providers Router

Endpoints:
- GET /providers - List embedding providers catalog with live status (default) or AI registry if format=registry
- GET /providers/registry - List all supported AI providers with their registry metadata
- POST /providers/{provider_id}/connect - Connect a provider from the catalog
- POST /providers/{provider_id}/disconnect - Disconnect a provider from the catalog
"""

from typing import List, Optional, Union

from fastapi import APIRouter, Query

from api.credentials_service import check_env_configured
from api.models import ProviderInfoResponse
from open_notebook.ai.provider_registry import PROVIDERS
from open_notebook.providers.service import (
    ProviderConnectRequest,
    ProviderConnectResponse,
    ProviderDisconnectResponse,
    ProviderStatusResponse,
    connect_provider,
    disconnect_provider,
    get_providers_with_status,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/registry", response_model=List[ProviderInfoResponse])
async def list_provider_registry():
    """List all supported AI providers with their registry metadata."""
    return [
        ProviderInfoResponse(
            name=spec.name,
            display_name=spec.display_name,
            modalities=list(spec.modalities),
            docs_url=spec.docs_url,
            env_configured=check_env_configured(spec.name),
        )
        for spec in PROVIDERS.values()
    ]


@router.get("", response_model=Union[List[ProviderStatusResponse], List[ProviderInfoResponse]])
async def list_providers(format: Optional[str] = Query(None)):
    """
    List providers.
    - Default: returns embedding provider store catalog with live status.
    - format=registry: returns AI provider registry metadata (backward-compatibility).
    """
    if format == "registry":
        return await list_provider_registry()
    return await get_providers_with_status()


@router.post("/{provider_id}/connect", response_model=ProviderConnectResponse)
async def connect_provider_endpoint(
    provider_id: str,
    request: ProviderConnectRequest = ProviderConnectRequest(),
):
    """Connect a provider from the catalog."""
    return await connect_provider(provider_id, request)


@router.post("/{provider_id}/disconnect", response_model=ProviderDisconnectResponse)
async def disconnect_provider_endpoint(provider_id: str):
    """Disconnect a provider from the catalog."""
    return await disconnect_provider(provider_id)
