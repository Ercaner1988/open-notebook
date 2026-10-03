'use client'

import { useState } from 'react'
import Link from 'next/link'
import { formatDistanceToNow } from 'date-fns'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Loader2, Pause, Play, AlertCircle, CheckCircle2, ArrowUpToLine, ArrowDownToLine, X, RotateCcw } from 'lucide-react'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { embeddingQueueApi } from '@/lib/api/embedding-queue'
import type { QueueJob, QueueJobStatus, UnusedCredential } from '@/lib/api/embedding-queue'
import {
  useQueueSummary,
  useQueueJobs,
  useQueueAction,
  useUnembedded,
  useUnusedCredentials,
} from '@/lib/hooks/use-embedding-queue'
import { useDeleteCredential } from '@/lib/hooks/use-credentials'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getDateLocale } from '@/lib/utils/date-locale'

const JOB_LIMIT = 100

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  )
}

function SourceLink({ job }: { job: QueueJob }) {
  const { t } = useTranslation()
  const title = job.source_title || t('embeddingQueue.untitled')
  if (!job.source_id) return <span className="font-medium">{title}</span>
  return (
    <Link
      href={`/sources/${job.source_id}`}
      className="font-medium hover:underline truncate"
    >
      {title}
    </Link>
  )
}

function JobList({ status }: { status: QueueJobStatus }) {
  const { t, language } = useTranslation()
  const { data: jobs, isLoading, error } = useQueueJobs(status, JOB_LIMIT)

  const move = useQueueAction(
    ({ id, position }: { id: string; position: 'top' | 'bottom' }) => embeddingQueueApi.move(id, position),
    () => t('embeddingQueue.moved'),
  )
  const cancel = useQueueAction((id: string) => embeddingQueueApi.cancel(id), () => t('embeddingQueue.canceled'))
  const retry = useQueueAction((id: string) => embeddingQueueApi.retry(id), () => t('embeddingQueue.retried'))
  const retryAll = useQueueAction(
    () => embeddingQueueApi.retryFailed(),
    (r) => t('embeddingQueue.retriedAll', { count: r.queued }),
  )
  const busy = move.isPending || cancel.isPending || retry.isPending || retryAll.isPending

  if (isLoading) return <Loader2 className="h-4 w-4 animate-spin" />
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('embeddingQueue.loadFailed')}</AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="space-y-3">
      {status === 'failed' && !!jobs?.length && (
        <Button size="sm" variant="outline" disabled={busy} onClick={() => retryAll.mutate()}>
          {retryAll.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RotateCcw className="mr-2 h-4 w-4" />}
          {t('embeddingQueue.retryAll')}
        </Button>
      )}
      {!jobs?.length && <p className="text-sm text-muted-foreground">{t('embeddingQueue.empty')}</p>}
      <ul className="divide-y rounded-md border">
        {jobs?.map((job) => (
          <li key={job.id} className="flex flex-wrap items-center gap-2 p-3">
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex"><SourceLink job={job} /></div>
              {job.created && (
                <p className="text-xs text-muted-foreground">
                  {t('embeddingQueue.created', {
                    time: formatDistanceToNow(new Date(job.created), { addSuffix: true, locale: getDateLocale(language) }),
                  })}
                </p>
              )}
              {status === 'failed' && job.error_message && (
                <p className="text-xs text-destructive line-clamp-2 break-words" title={job.error_message}>
                  {job.error_message}
                </p>
              )}
            </div>
            {status === 'new' && (
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => move.mutate({ id: job.id, position: 'top' })}>
                  <ArrowUpToLine className="mr-1 h-4 w-4" />{t('embeddingQueue.moveTop')}
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => move.mutate({ id: job.id, position: 'bottom' })}>
                  <ArrowDownToLine className="mr-1 h-4 w-4" />{t('embeddingQueue.moveBottom')}
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => cancel.mutate(job.id)}>
                  <X className="mr-1 h-4 w-4" />{t('embeddingQueue.cancel')}
                </Button>
              </div>
            )}
            {status === 'failed' && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => retry.mutate(job.id)}>
                <RotateCcw className="mr-1 h-4 w-4" />{t('embeddingQueue.retry')}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {(jobs?.length ?? 0) >= JOB_LIMIT && (
        <p className="text-xs text-muted-foreground">{t('embeddingQueue.truncated', { limit: JOB_LIMIT })}</p>
      )}
    </div>
  )
}

function Maintenance() {
  const { t } = useTranslation()
  const [toDelete, setToDelete] = useState<UnusedCredential | null>(null)

  const test = useQueueAction(() => embeddingQueueApi.testEmbedding(), () => t('embeddingQueue.testDone'))
  const unembedded = useUnembedded()
  const enqueue = useQueueAction(
    () => embeddingQueueApi.enqueueUnembedded(),
    (r) => t('embeddingQueue.queuedSources', { count: r.queued }),
  )
  const unused = useUnusedCredentials()
  const deleteCredential = useDeleteCredential()

  const report = unembedded.data
  const testResult = test.data

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('embeddingQueue.maintenance')}</CardTitle>
        <CardDescription>{t('embeddingQueue.maintenanceDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Test embedding model */}
        <div className="space-y-3">
          <Button variant="outline" disabled={test.isPending} onClick={() => test.mutate()}>
            {test.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('embeddingQueue.testModel')}
          </Button>
          {testResult && (
            <Alert variant={testResult.ok ? 'default' : 'destructive'} className={testResult.ok ? '' : 'border-2'}>
              {testResult.ok ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertCircle className="h-4 w-4" />}
              <AlertDescription className={testResult.ok ? '' : 'font-semibold'}>
                {testResult.ok ? t('embeddingQueue.testOk') : t('embeddingQueue.testFailed')}
                {testResult.model_id ? ` (${testResult.model_id})` : ''}: {testResult.message}
              </AlertDescription>
            </Alert>
          )}
        </div>

        {/* Unembedded sources */}
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={unembedded.isFetching} onClick={() => unembedded.refetch()}>
              {unembedded.isFetching && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('embeddingQueue.findUnembedded')}
            </Button>
            {report && report.with_text.length > 0 && (
              <Button disabled={enqueue.isPending} onClick={() => enqueue.mutate()}>
                {enqueue.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('embeddingQueue.queueAllWithText')}
              </Button>
            )}
          </div>
          {report && (
            <div className="space-y-2 text-sm">
              <p>{t('embeddingQueue.withText', { count: report.with_text.length })}</p>
              <p>{t('embeddingQueue.emptyText', { count: report.empty_text.length })}</p>
              {report.empty_text.length > 0 && (
                <ul className="max-h-48 overflow-y-auto rounded-md border divide-y">
                  {report.empty_text.map((s) => (
                    <li key={s.source_id} className="p-2">
                      <Link href={`/sources/${s.source_id}`} className="hover:underline">
                        {s.title || t('embeddingQueue.untitled')}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {/* Unused credentials */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{t('embeddingQueue.unusedCredentials')}</h3>
          {unused.isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
          {unused.data && unused.data.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('embeddingQueue.noUnusedCredentials')}</p>
          )}
          <ul className="divide-y rounded-md border empty:hidden">
            {unused.data?.map((c) => (
              <li key={c.id} className="flex items-center gap-2 p-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium truncate">{c.name}</p>
                  <p className="text-xs text-muted-foreground truncate">
                    {c.provider}{c.base_url ? ` · ${c.base_url}` : ''}
                  </p>
                </div>
                <Button size="sm" variant="destructive" disabled={deleteCredential.isPending} onClick={() => setToDelete(c)}>
                  {t('common.delete')}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>

      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title={t('embeddingQueue.deleteCredentialTitle')}
        description={t('embeddingQueue.deleteCredentialConfirm', { name: toDelete?.name ?? '' })}
        confirmText={t('common.delete')}
        confirmVariant="destructive"
        isLoading={deleteCredential.isPending}
        onConfirm={() => {
          if (!toDelete) return
          deleteCredential.mutate(
            { credentialId: toDelete.id },
            { onSettled: () => setToDelete(null), onSuccess: () => unused.refetch() },
          )
        }}
      />
    </Card>
  )
}

export function EmbeddingQueue() {
  const { t } = useTranslation()
  const { data: summary, error } = useQueueSummary()

  const pause = useQueueAction(() => embeddingQueueApi.pause(), () => t('embeddingQueue.pausedToast'))
  const resume = useQueueAction(() => embeddingQueueApi.resume(), () => t('embeddingQueue.resumedToast'))
  const toggling = pause.isPending || resume.isPending

  const eta = summary?.eta_minutes
  const etaText =
    eta == null
      ? '—'
      : eta < 60
        ? t('embeddingQueue.etaMinutes', { minutes: Math.max(1, Math.round(eta)) })
        : t('embeddingQueue.etaHours', { hours: Math.floor(eta / 60), minutes: Math.round(eta % 60) })
  const current = summary?.running[0]

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {t('embeddingQueue.title')}
            {summary && (
              <Badge variant={summary.paused ? 'destructive' : 'secondary'}>
                {summary.paused ? t('embeddingQueue.statePaused') : t('embeddingQueue.stateActive')}
              </Badge>
            )}
          </CardTitle>
          <CardDescription>{t('embeddingQueue.desc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{t('embeddingQueue.loadFailed')}</AlertDescription>
            </Alert>
          )}
          {summary && (
            <>
              <Button
                variant={summary.paused ? 'default' : 'outline'}
                disabled={toggling}
                onClick={() => (summary.paused ? resume.mutate() : pause.mutate())}
              >
                {toggling ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : summary.paused ? (
                  <Play className="mr-2 h-4 w-4" />
                ) : (
                  <Pause className="mr-2 h-4 w-4" />
                )}
                {summary.paused ? t('embeddingQueue.resume') : t('embeddingQueue.pause')}
              </Button>

              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label={t('embeddingQueue.waiting')} value={summary.counts.new} />
                <Stat label={t('embeddingQueue.running')} value={summary.counts.running} />
                <Stat label={t('embeddingQueue.completed')} value={summary.counts.completed} />
                <Stat label={t('embeddingQueue.failed')} value={summary.counts.failed} />
              </div>

              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label={t('embeddingQueue.chunksEmbedded')} value={summary.embedded_chunks.toLocaleString()} />
                <Stat
                  label={t('embeddingQueue.rate')}
                  value={summary.rate_chunks_per_min == null ? '—' : t('embeddingQueue.rateValue', { rate: Math.round(summary.rate_chunks_per_min) })}
                />
                <Stat label={t('embeddingQueue.eta')} value={etaText} />
                <Stat label={t('embeddingQueue.remainingChars')} value={t('embeddingQueue.charsValue', { chars: summary.pending_chars.toLocaleString() })} />
              </div>

              {current && (
                <p className="text-sm">
                  <span className="text-muted-foreground">{t('embeddingQueue.currentlyRunning')}: </span>
                  <span className="font-medium">{current.source_title || t('embeddingQueue.untitled')}</span>
                </p>
              )}
            </>
          )}

          <Tabs defaultValue="new">
            <TabsList>
              <TabsTrigger value="new">{t('embeddingQueue.waiting')}</TabsTrigger>
              <TabsTrigger value="running">{t('embeddingQueue.running')}</TabsTrigger>
              <TabsTrigger value="failed">{t('embeddingQueue.failed')}</TabsTrigger>
              <TabsTrigger value="completed">{t('embeddingQueue.completed')}</TabsTrigger>
            </TabsList>
            {(['new', 'running', 'failed', 'completed'] as const).map((s) => (
              <TabsContent key={s} value={s} className="mt-4">
                <JobList status={s} />
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      <Maintenance />
    </div>
  )
}
