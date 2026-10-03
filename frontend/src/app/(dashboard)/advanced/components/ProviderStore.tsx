'use client'

import { useState } from 'react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import {
  Loader2,
  AlertCircle,
  ExternalLink,
  WifiOff,
  Radio,
  Server,
  CheckCircle2,
} from 'lucide-react'
import {
  useProviderStore,
  useConnectProvider,
  useDisconnectProvider,
} from '@/lib/hooks/use-providers'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { ProviderStoreItem } from '@/lib/api/providers'
import { useToast } from '@/lib/hooks/use-toast'

export function ProviderStore() {
  const { t, language } = useTranslation()
  const { toast } = useToast()
  const { data: providers, isLoading, isError } = useProviderStore()
  const connectMutation = useConnectProvider()
  const disconnectMutation = useDisconnectProvider()

  // State for 409 Dimension Mismatch Confirmation Dialog
  const [mismatchDialog, setMismatchDialog] = useState<{
    open: boolean
    providerId: string | null
    detail: string
  }>({
    open: false,
    providerId: null,
    detail: '',
  })

  const isBusy = connectMutation.isPending || disconnectMutation.isPending

  const handleConnect = async (providerId: string, makeDefault: boolean) => {
    try {
      await connectMutation.mutateAsync({
        id: providerId,
        params: { make_default: makeDefault },
      })
    } catch (err: any) {
      if (err?.response?.status === 409) {
        setMismatchDialog({
          open: true,
          providerId,
          detail: err.response.data?.detail || t('providers.dimensionMismatchDesc'),
        })
      }
    }
  }

  const handleConfirmMismatch = async () => {
    if (!mismatchDialog.providerId) return
    const id = mismatchDialog.providerId
    setMismatchDialog({ open: false, providerId: null, detail: '' })
    try {
      await connectMutation.mutateAsync({
        id,
        params: { make_default: true, confirm_dimension_mismatch: true },
      })
    } catch (err: any) {
      toast({
        variant: 'destructive',
        title: t('providers.connectError'),
        description: err?.response?.data?.detail || err.message,
      })
    }
  }

  const handleDisconnect = (item: ProviderStoreItem) => {
    if (item.status === 'default') {
      toast({
        variant: 'destructive',
        title: t('providers.disconnectError'),
        description: t('providers.defaultCannotBeDisconnected'),
      })
      return
    }
    disconnectMutation.mutate(item.id)
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Server className="h-5 w-5 text-primary" />
                <CardTitle>{t('providers.title')}</CardTitle>
              </div>
              <CardDescription>{t('providers.desc')}</CardDescription>
            </div>
            {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {isError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{t('providers.loadFailed')}</AlertDescription>
            </Alert>
          )}

          {!isLoading && (!providers || providers.length === 0) && (
            <p className="text-sm text-muted-foreground">{t('providers.emptyCatalog')}</p>
          )}

          <div className="grid grid-cols-1 gap-4">
            {providers?.map((item) => {
              const localizedDesc =
                language === 'tr' ? item.description.tr : item.description.en

              return (
                <div
                  key={item.id}
                  className="rounded-lg border bg-card p-4 text-card-foreground shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4"
                >
                  <div className="space-y-2 min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold text-base tracking-tight">{item.name}</h3>
                      <Badge variant="outline" className="font-mono text-xs">
                        {item.model} • {item.dimension}d
                      </Badge>
                      {item.status === 'default' && (
                        <Badge className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1 text-xs">
                          <CheckCircle2 className="h-3 w-3" />
                          {t('providers.statusDefault')}
                        </Badge>
                      )}
                      {item.status === 'connected' && (
                        <Badge variant="secondary" className="gap-1 text-xs">
                          <span className="h-2 w-2 rounded-full bg-teal-500 inline-block" />
                          {t('providers.statusConnected')}
                        </Badge>
                      )}
                      {item.status === 'running' && (
                        <Badge variant="secondary" className="gap-1 text-xs">
                          <span className="h-2 w-2 rounded-full bg-blue-500 inline-block animate-pulse" />
                          {t('providers.statusRunning')}
                        </Badge>
                      )}
                      {item.status === 'not_detected' && (
                        <Badge variant="outline" className="text-muted-foreground gap-1 text-xs">
                          <span className="h-2 w-2 rounded-full bg-muted-foreground/40 inline-block" />
                          {t('providers.statusNotDetected')}
                        </Badge>
                      )}
                      {(item.status === 'connected' || item.status === 'default') && !item.is_running && (
                        <span className="text-xs text-amber-500 flex items-center gap-1">
                          <WifiOff className="h-3 w-3" />
                          {t('providers.offlineNotice')}
                        </span>
                      )}
                    </div>

                    <p className="text-sm text-muted-foreground">{localizedDesc}</p>

                    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      <span className="font-mono bg-muted/60 px-1.5 py-0.5 rounded">
                        {item.base_url}
                      </span>
                      {item.notes && <span className="italic">{item.notes}</span>}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 shrink-0">
                    <Button
                      variant="outline"
                      size="sm"
                      asChild
                      title={t('providers.download')}
                    >
                      <a
                        href={item.download_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center"
                      >
                        <ExternalLink className="h-3.5 w-3.5 mr-1" />
                        {t('providers.download')}
                      </a>
                    </Button>

                    {(item.status === 'not_detected' || item.status === 'running') && (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={isBusy}
                          onClick={() => handleConnect(item.id, false)}
                        >
                          {connectMutation.isPending && (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                          )}
                          {t('providers.connect')}
                        </Button>
                        <Button
                          size="sm"
                          disabled={isBusy}
                          onClick={() => handleConnect(item.id, true)}
                        >
                          {connectMutation.isPending && (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                          )}
                          {t('providers.connectAsDefault')}
                        </Button>
                      </>
                    )}

                    {item.status === 'connected' && (
                      <>
                        <Button
                          size="sm"
                          disabled={isBusy}
                          onClick={() => handleConnect(item.id, true)}
                        >
                          {connectMutation.isPending && (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                          )}
                          {t('providers.makeDefault')}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-destructive hover:bg-destructive/10"
                          disabled={isBusy}
                          onClick={() => handleDisconnect(item)}
                        >
                          {disconnectMutation.isPending && (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                          )}
                          {t('providers.disconnect')}
                        </Button>
                      </>
                    )}

                    {item.status === 'default' && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-muted-foreground"
                        disabled={isBusy}
                        onClick={() => handleDisconnect(item)}
                      >
                        {disconnectMutation.isPending && (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        )}
                        {t('providers.disconnect')}
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={mismatchDialog.open}
        onOpenChange={(open) =>
          setMismatchDialog((prev) => ({ ...prev, open }))
        }
        title={t('providers.dimensionMismatchTitle')}
        description={mismatchDialog.detail}
        confirmText={t('providers.confirmDimensionMismatch')}
        confirmVariant="default"
        onConfirm={handleConfirmMismatch}
        isLoading={connectMutation.isPending}
      />
    </>
  )
}
