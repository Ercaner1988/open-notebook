import apiClient from './client'

// Types for AI providers registry API (Settings > Models)
export interface ProviderInfo {
  name: string
  display_name: string
  modalities: string[]
  docs_url?: string | null
  env_configured: boolean
}

// Types for Embedding Provider Store (Advanced > Providers)
export interface ProviderDescription {
  en: string
  tr: string
}

export type ProviderStatus = 'not_detected' | 'running' | 'connected' | 'default'

export interface ProviderStoreItem {
  id: string
  name: string
  description: ProviderDescription
  homepage?: string | null
  download_url: string
  kind: string
  base_url: string
  probe_ports: number[]
  health_path: string
  model: string
  dimension: number
  provider_type: string
  credential_name: string
  notes?: string | null
  status: ProviderStatus
  is_running: boolean
  detected_url?: string | null
  connected_credential_id?: string | null
  connected_model_id?: string | null
}

export interface ProviderConnectParams {
  base_url?: string
  make_default?: boolean
  confirm_dimension_mismatch?: boolean
}

export interface ProviderConnectResponse {
  ok: boolean
  credential_id: string
  model_id: string
  is_default: boolean
  test_result: { ok: boolean; message: string }
  message?: string
}

export interface ProviderDisconnectResponse {
  ok: boolean
  message: string
  deleted_models: number
}

export const providerStoreApi = {
  /**
   * List embedding providers catalog with live status.
   */
  list: async (): Promise<ProviderStoreItem[]> => {
    const response = await apiClient.get<ProviderStoreItem[]>('/providers')
    return response.data
  },

  /**
   * Connect a provider from the catalog.
   */
  connect: async (
    id: string,
    params?: ProviderConnectParams
  ): Promise<ProviderConnectResponse> => {
    const response = await apiClient.post<ProviderConnectResponse>(
      `/providers/${id}/connect`,
      params || {}
    )
    return response.data
  },

  /**
   * Disconnect a provider from the catalog.
   */
  disconnect: async (id: string): Promise<ProviderDisconnectResponse> => {
    const response = await apiClient.post<ProviderDisconnectResponse>(
      `/providers/${id}/disconnect`
    )
    return response.data
  },
}

export const providersApi = {
  /**
   * List all supported AI providers with their registry metadata.
   */
  list: async (): Promise<ProviderInfo[]> => {
    const response = await apiClient.get<ProviderInfo[]>('/providers/registry')
    return response.data
  },

  // Aliases for provider store
  store: providerStoreApi.list,
  connect: providerStoreApi.connect,
  disconnect: providerStoreApi.disconnect,
}
