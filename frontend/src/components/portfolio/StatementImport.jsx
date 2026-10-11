import { useRef, useState } from 'react'
import { CheckCircle2, FileSpreadsheet, Upload } from 'lucide-react'
import Button from '../Button'
import Card from '../Card'
import ErrorBanner from '../ErrorBanner'
import { getErrorMessage } from '../../api/client'
import { importStatement } from '../../api/portfolio'
import { formatDate } from '../../utils/format'

const MAX_BYTES = 5 * 1024 * 1024

function Stat({ label, value }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-base font-semibold text-slate-900">{value}</p>
    </div>
  )
}

export default function StatementImport({ onImported }) {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [rowErrors, setRowErrors] = useState([])

  function pick(selected) {
    setReport(null)
    setError('')
    setRowErrors([])
    if (!selected) return
    if (!selected.name.toLowerCase().endsWith('.csv')) {
      setFile(null)
      setError('Please choose a .csv file.')
      return
    }
    if (selected.size > MAX_BYTES) {
      setFile(null)
      setError('File is larger than 5 MB.')
      return
    }
    setFile(selected)
  }

  function handleDrop(event) {
    event.preventDefault()
    setDragging(false)
    pick(event.dataTransfer.files?.[0])
  }

  async function handleUpload() {
    if (!file) return
    setUploading(true)
    setError('')
    setRowErrors([])
    try {
      const result = await importStatement(file)
      setReport(result)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
      onImported?.(result)
    } catch (err) {
      setError(getErrorMessage(err))
      const detail = err.response?.data?.detail
      setRowErrors(Array.isArray(detail?.row_errors) ? detail.row_errors : [])
    } finally {
      setUploading(false)
    }
  }

  return (
    <Card title="Import Zerodha Tradebook">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click()
        }}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
          dragging ? 'border-indigo-400 bg-indigo-50' : 'border-slate-300 hover:border-indigo-300 hover:bg-slate-50'
        }`}
      >
        <Upload size={24} className="text-slate-400" />
        <p className="mt-2 text-sm font-medium text-slate-700">Drag a Tradebook CSV here, or click to choose</p>
        <p className="mt-1 text-xs text-slate-500">From Zerodha Console, Reports, Tradebook. Max 5 MB.</p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(event) => pick(event.target.files?.[0])}
        />
      </div>

      {file && (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-slate-200 px-3 py-2">
          <div className="flex min-w-0 items-center gap-2 text-sm text-slate-700">
            <FileSpreadsheet size={18} className="shrink-0 text-green-600" />
            <span className="truncate">{file.name}</span>
          </div>
          <Button size="sm" onClick={handleUpload} loading={uploading}>
            {uploading ? 'Importing...' : 'Import'}
          </Button>
        </div>
      )}

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {rowErrors.length > 0 && (
        <div className="mt-3 max-h-56 overflow-y-auto rounded-xl border border-red-200">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-red-50 text-xs uppercase text-red-700">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Row</th>
                <th className="px-3 py-2 text-left font-medium">Problem</th>
              </tr>
            </thead>
            <tbody>
              {rowErrors.map((item, index) => (
                <tr key={`${item.row}-${index}`} className="border-t border-red-100">
                  <td className="px-3 py-2 align-top text-slate-700">{item.row ?? '-'}</td>
                  <td className="px-3 py-2 text-slate-700">{item.error ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {report && (
        <div className="mt-4">
          <p className="mb-3 flex items-center gap-2 text-sm font-medium text-green-700">
            <CheckCircle2 size={16} />
            Import complete
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Rows in file" value={report.rows_in_file} />
            <Stat label="Inserted" value={report.inserted} />
            <Stat label="Duplicates skipped" value={report.duplicates_skipped} />
            <Stat label="Non-equity skipped" value={report.non_equity_skipped} />
          </div>
          <p className="mt-3 text-sm text-slate-600">
            Date range:{' '}
            {report.date_range
              ? `${formatDate(report.date_range[0])} to ${formatDate(report.date_range[1])}`
              : '-'}
          </p>
        </div>
      )}

      <p className="mt-4 text-xs text-slate-500">
        Imported trades are stored as transaction history and used to learn your investing behaviour. They do not
        change your holdings.
      </p>
    </Card>
  )
}
