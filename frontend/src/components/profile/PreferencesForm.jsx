import { useState } from 'react'
import { Save } from 'lucide-react'
import Button from '../Button'
import Card from '../Card'
import ErrorBanner from '../ErrorBanner'
import OptionCards from './OptionCards'
import { useToast } from '../Toast'
import { getErrorMessage } from '../../api/client'
import { updateProfile } from '../../api/profile'
import { HORIZON_OPTIONS, RISK_OPTIONS } from '../../utils/profile'

const GOALS_MAX = 2000
const AMOUNT_MAX = 999999999999.99

function initialForm(profile) {
  return {
    stated_risk_appetite: profile?.stated_risk_appetite ?? null,
    stated_investment_horizon: profile?.stated_investment_horizon ?? null,
    goals: profile?.goals ?? '',
    monthly_investment_amount:
      profile?.monthly_investment_amount === null || profile?.monthly_investment_amount === undefined
        ? ''
        : String(profile.monthly_investment_amount),
  }
}

function validateAmount(raw) {
  if (raw === '') return ''
  const amount = Number(raw)
  if (!Number.isFinite(amount)) return 'Enter a number.'
  if (amount < 0) return 'The amount cannot be negative.'
  if (amount > AMOUNT_MAX) return 'That amount is too large.'
  if (!/^\d+(\.\d{1,2})?$/.test(raw.trim())) return 'Use at most 2 decimal places.'
  return ''
}

export default function PreferencesForm({ profile, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState(() => initialForm(profile))
  const [amountError, setAmountError] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  function set(name, value) {
    setForm((current) => ({ ...current, [name]: value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    const problem = validateAmount(form.monthly_investment_amount)
    setAmountError(problem)
    if (problem) return

    setSaving(true)
    try {
      const saved = await updateProfile({
        stated_risk_appetite: form.stated_risk_appetite,
        stated_investment_horizon: form.stated_investment_horizon,
        goals: form.goals.trim() ? form.goals.trim() : null,
        monthly_investment_amount: form.monthly_investment_amount === '' ? null : Number(form.monthly_investment_amount),
      })
      onSaved(saved)
      setForm(initialForm(saved))
      toast.success('Preferences saved.')
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Your preferences">
      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        <div>
          <p className="mb-2 text-sm font-medium text-slate-700">Risk preference</p>
          <OptionCards
            name="Risk preference"
            options={RISK_OPTIONS}
            value={form.stated_risk_appetite}
            onChange={(value) => set('stated_risk_appetite', value)}
          />
        </div>

        <div>
          <p className="mb-2 text-sm font-medium text-slate-700">Investment horizon</p>
          <OptionCards
            name="Investment horizon"
            options={HORIZON_OPTIONS}
            value={form.stated_investment_horizon}
            onChange={(value) => set('stated_investment_horizon', value)}
          />
          <p className="mt-2 text-xs text-slate-400">Click a selected card again to clear it.</p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <label className="block text-sm font-medium text-slate-700 md:col-span-2">
            Goals
            <textarea
              rows={4}
              maxLength={GOALS_MAX}
              value={form.goals}
              onChange={(event) => set('goals', event.target.value)}
              placeholder="e.g. Build a retirement corpus, save for a house in 5 years"
              className="mt-1 w-full resize-y rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
            <span className="mt-1 block text-right text-xs font-normal text-slate-400">
              {form.goals.length} / {GOALS_MAX}
            </span>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Monthly investment (₹)
            <div className="relative mt-1">
              <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-slate-400">
                ₹
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                value={form.monthly_investment_amount}
                onChange={(event) => {
                  set('monthly_investment_amount', event.target.value)
                  if (amountError) setAmountError('')
                }}
                placeholder="10000"
                className={`w-full rounded-xl border py-2 pl-7 pr-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 ${
                  amountError ? 'border-red-400' : 'border-slate-300'
                }`}
              />
            </div>
            {amountError && <span className="mt-1 block text-xs font-normal text-red-600">{amountError}</span>}
          </label>
        </div>

        {error && <ErrorBanner message={error} />}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Changes take effect the next time the system classifies you, for example on your next analysis.
          </p>
          <Button type="submit" icon={Save} loading={saving}>
            Save preferences
          </Button>
        </div>
      </form>
    </Card>
  )
}
