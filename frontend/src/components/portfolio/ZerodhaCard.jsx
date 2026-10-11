import { useState } from 'react'
import { Link2, RefreshCw, Unplug } from 'lucide-react'
import Button from '../Button'
import Card from '../Card'
import ConfirmDialog from '../ConfirmDialog'
import ErrorBanner from '../ErrorBanner'
import Spinner from '../Spinner'
import { useToast } from '../Toast'
import useApi from '../../hooks/useApi'
import { getErrorMessage } from '../../api/client'
import { disconnectZerodha, getZerodhaConnectUrl, getZerodhaStatus, syncZerodha } from '../../api/portfolio'
import { formatDateTime } from '../../utils/format'

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3 py-1 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{value}</span>
    </div>
  )
}

export default function ZerodhaCard({ onHoldingsChanged }) {
  const toast = useToast()
  const status = useApi(getZerodhaStatus)
  const [busy, setBusy] = useState('')
  const [actionError, setActionError] = useState('')
  const [syncReport, setSyncReport] = useState(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  async function handleConnect() {
    setBusy('connect')
    setActionError('')
    try {
      const { login_url: loginUrl } = await getZerodhaConnectUrl()
      window.location.href = loginUrl
    } catch (err) {
      setActionError(getErrorMessage(err))
      setBusy('')
    }
  }

  async function handleSync() {
    setBusy('sync')
    setActionError('')
    setSyncReport(null)
    try {
      const report = await syncZerodha()
      setSyncReport(report)
      toast.success('Zerodha holdings synced.')
      onHoldingsChanged()
      status.reload({ silent: true })
    } catch (err) {
      setActionError(getErrorMessage(err))
      if (err.response?.status === 409) status.reload({ silent: true })
    } finally {
      setBusy('')
    }
  }

  async function handleDisconnect() {
    setBusy('disconnect')
    setActionError('')
    try {
      await disconnectZerodha()
      setConfirmOpen(false)
      setSyncReport(null)
      toast.success('Zerodha disconnected. Synced holdings were removed.')
      onHoldingsChanged()
      status.reload({ silent: true })
    } catch (err) {
      setActionError(getErrorMessage(err))
      setConfirmOpen(false)
    } finally {
      setBusy('')
    }
  }

  const connected = status.data?.connected

  return (
    <Card
      title="Zerodha Kite"
      actions={
        status.data && (
          <span
            className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
              connected ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'
            }`}
          >
            {connected ? 'Connected' : 'Not connected'}
          </span>
        )
      }
    >
      {status.loading ? (
        <Spinner label="Checking connection" />
      ) : status.error ? (
        <ErrorBanner message={status.error.message} onRetry={() => status.reload()} />
      ) : (
        <>
          {connected ? (
            <div className="divide-y divide-slate-100">
              <Row label="Zerodha user" value={status.data.broker_user_id || '-'} />
              <Row label="Last synced" value={formatDateTime(status.data.last_synced_at)} />
              <Row label="Session expires" value={formatDateTime(status.data.expires_at)} />
            </div>
          ) : (
            <p className="text-sm text-slate-600">
              Connect your Zerodha account to sync your demat holdings automatically. Synced holdings are
              read-only here.
            </p>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            {connected ? (
              <>
                <Button icon={RefreshCw} onClick={handleSync} loading={busy === 'sync'} disabled={Boolean(busy)}>
                  Sync holdings now
                </Button>
                <Button
                  variant="secondary"
                  icon={Unplug}
                  onClick={() => setConfirmOpen(true)}
                  disabled={Boolean(busy)}
                >
                  Disconnect
                </Button>
              </>
            ) : (
              <Button icon={Link2} onClick={handleConnect} loading={busy === 'connect'} disabled={Boolean(busy)}>
                Connect Zerodha
              </Button>
            )}
          </div>

          {actionError && (
            <div className="mt-4">
              <ErrorBanner message={actionError} />
            </div>
          )}

          {syncReport && (
            <div className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-700">
              Updated {syncReport.holdings_upserted}, removed {syncReport.holdings_removed}, skipped{' '}
              {syncReport.skipped}.
            </div>
          )}
        </>
      )}

      <p className="mt-4 text-xs text-slate-400">
        Note: the real Zerodha login flow is untested until a real Kite account connects.
      </p>

      <ConfirmDialog
        open={confirmOpen}
        title="Disconnect Zerodha?"
        message="This forgets your Zerodha session and removes all holdings synced from Zerodha. Manual holdings stay."
        confirmLabel="Disconnect"
        loading={busy === 'disconnect'}
        onConfirm={handleDisconnect}
        onCancel={() => setConfirmOpen(false)}
      />
    </Card>
  )
}
