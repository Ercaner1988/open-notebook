import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  providerStoreApi,
  providersApi,
  ProviderConnectParams,
} from '@/lib/api/providers'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

export const PROVIDER_QUERY_KEYS = {
  providers: ['providers'] as const,
}

export const PROVIDER_STORE_QUERY_KEYS = {
  all: ['provider-store'] as const,
  list: ['provider-store', 'list'] as const,
}

const POLL_INTERVAL_MS = 5000

/**
 * Hook to list all supported AI providers (from the backend provider
 * registry). Used in Settings > Models.
 */
export function useProviders() {
  return useQuery({
    queryKey: PROVIDER_QUERY_KEYS.providers,
    queryFn: () => providersApi.list(),
    staleTime: Infinity,
    gcTime: 24 * 60 * 60 * 1000,
  })
}

/**
 * Hook to list local embedding providers catalog with live status.
 * Polled every 5 seconds; TanStack Query pauses when the tab/page is hidden.
 */
export function useProviderStore() {
  return useQuery({
    queryKey: PROVIDER_STORE_QUERY_KEYS.list,
    queryFn: () => providerStoreApi.list(),
    refetchInterval: POLL_INTERVAL_MS,
  })
}

/**
 * Hook to connect a provider from the catalog.
 */
export function useConnectProvider() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({
      id,
      params,
    }: {
      id: string
      params?: ProviderConnectParams
    }) => providerStoreApi.connect(id, params),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: PROVIDER_STORE_QUERY_KEYS.all })
      queryClient.invalidateQueries({ queryKey: ['model-defaults'] })
      queryClient.invalidateQueries({ queryKey: ['models'] })
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      toast({
        title: t('providers.connectedSuccess'),
        description: res.test_result?.message || res.message,
      })
    },
    onError: (err: any) => {
      const status = err?.response?.status
      // 409 Dimension mismatch is handled by dialog in component
      if (status !== 409) {
        toast({
          variant: 'destructive',
          title: t('providers.connectError'),
          description: err?.response?.data?.detail || err.message,
        })
      }
    },
  })
}

/**
 * Hook to disconnect a provider from the catalog.
 */
export function useDisconnectProvider() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (id: string) => providerStoreApi.disconnect(id),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: PROVIDER_STORE_QUERY_KEYS.all })
      queryClient.invalidateQueries({ queryKey: ['model-defaults'] })
      queryClient.invalidateQueries({ queryKey: ['models'] })
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      toast({
        title: t('providers.disconnectedSuccess'),
        description: res.message,
      })
    },
    onError: (err: any) => {
      toast({
        variant: 'destructive',
        title: t('providers.disconnectError'),
        description: err?.response?.data?.detail || err.message,
      })
    },
  })
}
