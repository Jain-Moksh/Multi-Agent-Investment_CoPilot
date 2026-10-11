import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, RefreshCw } from 'lucide-react'
import Button from '../components/Button'
import Card from '../components/Card'
import ConfirmDialog from '../components/ConfirmDialog'
import ErrorBanner from '../components/ErrorBanner'
import PageHeader from '../components/PageHeader'
import Spinner from '../components/Spinner'
import { useToast } from '../components/Toast'
import HoldingModal from '../components/portfolio/HoldingModal'
import HoldingsTable from '../components/portfolio/HoldingsTable'
import StatementImport from '../components/portfolio/StatementImport'
import SummaryCards from '../components/portfolio/SummaryCards'
import ZerodhaCard from '../components/portfolio/ZerodhaCard'
import useApi from '../hooks/useApi'
import { getErrorMessage } from '../api/client'
import { deleteHolding, getSummary } from '../api/portfolio'

const ZERODHA_RESULTS = {
  connected: { variant: 'success', message: 'Zerodha connected. Your holdings were synced.' },
  cancelled: { variant: 'error', message: 'Zerodha login was cancelled.' },
  invalid_state: { variant: 'error', message: 'The Zerodha login link expired or was invalid. Please connect again.' },
  error: { variant: 'error', message: 'Could not complete the Zerodha connection. Please try again.' },
}

export default function Portfolio() {
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const handledZerodha = useRef(false)
  const summary = useApi(getSummary)
  const [modal, setModal] = useState({ open: false, holding: null })
  const [toDelete, setToDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  useEffect(() => {
    const result = searchParams.get('zerodha')
    if (!result || handledZerodha.current) return
    handledZerodha.current = true
    const outcome = ZERODHA_RESULTS[result] || ZERODHA_RESULTS.error
    toast[outcome.variant](outcome.message)
    const next = new URLSearchParams(searchParams)
    next.delete('zerodha')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams, toast])

  function refreshSummary() {
    summary.reload({ silent: true })
  }

  function handleSaved(saved, isEdit) {
    setModal({ open: false, holding: null })
    toast.success(isEdit ? `${saved.symbol} updated.` : `${saved.symbol} added.`)
    refreshSummary()
  }

  async function handleDelete() {
    setDeleting(true)
    setDeleteError('')
    try {
      await deleteHolding(toDelete.id)
      toast.success(`${toDelete.symbol} deleted.`)
      setToDelete(null)
      refreshSummary()
    } catch (err) {
      setDeleteError(getErrorMessage(err))
    } finally {
      setDeleting(false)
    }
  }

  const data = summary.data

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolio"
        subtitle="Your holdings valued at the latest market prices."
        actions={
          <>
            <Button variant="secondary" icon={RefreshCw} onClick={() => summary.reload()} disabled={summary.loading}>
              Refresh
            </Button>
            <Button icon={Plus} onClick={() => setModal({ open: true, holding: null })}>
              Add holding
            </Button>
          </>
        }
      />

      {summary.loading && !data ? (
        <Card>
          <Spinner label="Loading your portfolio" />
        </Card>
      ) : summary.error && !data ? (
        <ErrorBanner message={summary.error.message} onRetry={() => summary.reload()} />
      ) : (
        <>
          {summary.error && <ErrorBanner message={summary.error.message} onRetry={() => summary.reload()} />}
          <SummaryCards totals={data?.totals} />
          <Card
            title="Holdings"
            actions={
              data && (
                <span className="text-xs text-slate-500">
                  {data.priced_holdings} of {data.holdings_count} with a live price
                </span>
              )
            }
          >
            <HoldingsTable
              holdings={data?.holdings || []}
              onAdd={() => setModal({ open: true, holding: null })}
              onEdit={(holding) => setModal({ open: true, holding })}
              onDelete={(holding) => {
                setDeleteError('')
                setToDelete(holding)
              }}
            />
          </Card>
        </>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <StatementImport />
        <ZerodhaCard onHoldingsChanged={refreshSummary} />
      </div>

      {modal.open && (
        <HoldingModal
          key={modal.holding?.id ?? 'new'}
          holding={modal.holding}
          onClose={() => setModal({ open: false, holding: null })}
          onSaved={handleSaved}
        />
      )}

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="Delete holding?"
        message={toDelete ? `Remove ${toDelete.symbol} from your portfolio? This cannot be undone.` : ''}
        confirmLabel="Delete"
        loading={deleting}
        error={deleteError}
        onConfirm={handleDelete}
        onCancel={() => setToDelete(null)}
      />
    </div>
  )
}
