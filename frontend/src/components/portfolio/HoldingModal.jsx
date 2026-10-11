import { useState } from 'react'
import Button from '../Button'
import Modal from '../Modal'
import { getErrorMessage } from '../../api/client'
import { addHolding, updateHolding } from '../../api/portfolio'
import { ASSET_TYPES } from '../../utils/assets'

const INPUT_CLASS =
  'mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100 disabled:text-slate-500'

const EMPTY_FORM = { asset_type: 'stock', symbol: '', quantity: '', avg_buy_price: '' }

function validate(form) {
  const errors = {}
  if (!form.symbol.trim()) errors.symbol = 'Enter a symbol or name.'
  else if (form.symbol.trim().length > 60) errors.symbol = 'At most 60 characters.'
  if (!(Number(form.quantity) > 0)) errors.quantity = 'Quantity must be greater than 0.'
  if (form.avg_buy_price === '' || !(Number(form.avg_buy_price) >= 0)) {
    errors.avg_buy_price = 'Average buy price must be 0 or more.'
  }
  return errors
}

function initialForm(holding) {
  if (!holding) return EMPTY_FORM
  return {
    asset_type: holding.asset_type,
    symbol: holding.symbol,
    quantity: String(holding.quantity),
    avg_buy_price: String(holding.avg_buy_price),
  }
}

export default function HoldingModal({ holding, onClose, onSaved }) {
  const isEdit = Boolean(holding)
  const [form, setForm] = useState(() => initialForm(holding))
  const [fieldErrors, setFieldErrors] = useState({})
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  function update(name) {
    return (event) => setForm((current) => ({ ...current, [name]: event.target.value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    const errors = validate(form)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSaving(true)
    try {
      const amounts = { quantity: Number(form.quantity), avg_buy_price: Number(form.avg_buy_price) }
      const saved = isEdit
        ? await updateHolding(holding.id, amounts)
        : await addHolding({ asset_type: form.asset_type, symbol: form.symbol.trim(), ...amounts })
      onSaved(saved, isEdit)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      title={isEdit ? `Edit ${holding.symbol}` : 'Add holding'}
      onClose={saving ? () => {} : onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="holding-form" loading={saving}>
            {isEdit ? 'Save changes' : 'Add holding'}
          </Button>
        </>
      }
    >
      <form id="holding-form" onSubmit={handleSubmit} noValidate className="space-y-4">
        <label className="block text-sm font-medium text-slate-700">
          Asset type
          <select
            value={form.asset_type}
            onChange={update('asset_type')}
            disabled={isEdit}
            className={INPUT_CLASS}
          >
            {ASSET_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm font-medium text-slate-700">
          {form.asset_type === 'stock' ? 'Symbol' : 'Name'}
          <input
            type="text"
            value={form.symbol}
            onChange={update('symbol')}
            disabled={isEdit}
            placeholder={form.asset_type === 'stock' ? 'RELIANCE or RELIANCE.NS' : 'e.g. SBI FD 2027'}
            className={INPUT_CLASS}
          />
          {fieldErrors.symbol ? (
            <span className="mt-1 block text-xs font-normal text-red-600">{fieldErrors.symbol}</span>
          ) : (
            form.asset_type === 'stock' &&
            !isEdit && (
              <span className="mt-1 block text-xs font-normal text-slate-500">
                Symbols without .NS or .BO default to NSE.
              </span>
            )
          )}
        </label>

        {isEdit && (
          <p className="text-xs text-slate-500">To change the symbol or asset type, delete this holding and add a new one.</p>
        )}

        <div className="grid grid-cols-2 gap-4">
          <label className="block text-sm font-medium text-slate-700">
            Quantity
            <input
              type="number"
              step="any"
              min="0"
              value={form.quantity}
              onChange={update('quantity')}
              className={INPUT_CLASS}
            />
            {fieldErrors.quantity && (
              <span className="mt-1 block text-xs font-normal text-red-600">{fieldErrors.quantity}</span>
            )}
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Average buy price (₹)
            <input
              type="number"
              step="any"
              min="0"
              value={form.avg_buy_price}
              onChange={update('avg_buy_price')}
              className={INPUT_CLASS}
            />
            {fieldErrors.avg_buy_price && (
              <span className="mt-1 block text-xs font-normal text-red-600">{fieldErrors.avg_buy_price}</span>
            )}
          </label>
        </div>

        {error && (
          <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}
      </form>
    </Modal>
  )
}
