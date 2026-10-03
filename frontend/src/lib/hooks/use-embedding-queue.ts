import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { embeddingQueueApi, QueueJobStatus } from '@/lib/api/embedding-queue'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'

export const EMBEDDING_QUEUE_KEYS = {
  all: ['embedding-queue'] as const,
  summary: ['embedding-queue', 'summary'] as const,
  jobs: (status: QueueJobStatus) => ['embedding-queue', 'jobs', status] as const,
  unembedded: ['embedding-queue', 'unembedded'] as const,
  unusedCredentials: ['embedding-queue', 'unused-credentials'] as const,
}

const POLL_MS = 5000

export function useQueueSummary() {
  return useQuery({
    queryKey: EMBEDDING_QUEUE_KEYS.summary,
    queryFn: () => embeddingQueueApi.summary(),
    refetchInterval: POLL_MS,
  })
}

export function useQueueJobs(status: QueueJobStatus, limit = 100) {
  return useQuery({
    queryKey: EMBEDDING_QUEUE_KEYS.jobs(status),
    queryFn: () => embeddingQueueApi.jobs(status, limit),
    refetchInterval: POLL_MS,
  })
}

export function useUnembedded() {
  return useQuery({
    queryKey: EMBEDDING_QUEUE_KEYS.unembedded,
    queryFn: () => embeddingQueueApi.unembedded(),
    enabled: false, // only on demand ("Find unembedded sources")
  })
}

export function useUnusedCredentials() {
  return useQuery({
    queryKey: EMBEDDING_QUEUE_KEYS.unusedCredentials,
    queryFn: () => embeddingQueueApi.unusedCredentials(),
  })
}

/**
 * Generic mutating action: toasts success/failure, then refreshes the queue
 * queries (summary, jobs and the maintenance lists).
 */
export function useQueueAction<TVars = void, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  successMessage: (res: TRes) => string,
) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: fn,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: EMBEDDING_QUEUE_KEYS.all })
      toast({ title: t('common.success'), description: successMessage(res) })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: getApiErrorKey(error, t('embeddingQueue.actionFailed')),
        variant: 'destructive',
      })
    },
  })
}
