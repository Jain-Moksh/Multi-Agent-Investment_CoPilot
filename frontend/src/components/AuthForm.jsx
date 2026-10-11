import { useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, TrendingUp } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { getErrorMessage, safeNextPath } from '../api/client'
import Disclaimer from './Disclaimer'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const INPUT_CLASS =
  'mt-1 w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function validate({ email, password, confirm }, isLogin) {
  const errors = {}
  if (!EMAIL_PATTERN.test(email.trim())) errors.email = 'Enter a valid email address.'
  if (isLogin) {
    if (!password) errors.password = 'Enter your password.'
  } else {
    if (password.length < 8) errors.password = 'Password must be at least 8 characters.'
    else if (new TextEncoder().encode(password).length > 72) errors.password = 'Password must be at most 72 bytes.'
    if (confirm !== password) errors.confirm = 'Passwords do not match.'
  }
  return errors
}

function Field({ label, error, children }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      {children}
      {error && <span className="mt-1 block text-xs font-normal text-red-600">{error}</span>}
    </label>
  )
}

export default function AuthForm({ mode }) {
  const isLogin = mode === 'login'
  const { login, signup } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const expired = isLogin && searchParams.get('expired') === '1'
  const nextPath = safeNextPath(searchParams.get('next') || location.state?.from)
  const [values, setValues] = useState({ email: '', password: '', confirm: '' })
  const [fieldErrors, setFieldErrors] = useState({})
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function update(name) {
    return (event) => setValues((current) => ({ ...current, [name]: event.target.value }))
  }

  function inputClass(name) {
    return `${INPUT_CLASS} ${fieldErrors[name] ? 'border-red-400' : 'border-slate-300'}`
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    const errors = validate(values, isLogin)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      if (isLogin) await login(values.email.trim(), values.password)
      else await signup(values.email.trim(), values.password)
      navigate(isLogin ? nextPath : '/', { replace: true })
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 text-white">
            <TrendingUp size={26} />
          </div>
          <h1 className="mt-3 text-2xl font-semibold text-slate-900">Investment Copilot</h1>
          <p className="mt-1 text-sm text-slate-500">Personalized, explainable investment guidance</p>
        </div>

        <h2 className="mt-8 text-lg font-semibold text-slate-900">
          {isLogin ? 'Log in to your account' : 'Create your account'}
        </h2>

        {expired && !error && (
          <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800" role="status">
            Your session expired, please log in again
          </p>
        )}

        <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-4">
          <Field label="Email" error={fieldErrors.email}>
            <input
              type="email"
              autoComplete="email"
              value={values.email}
              onChange={update('email')}
              className={inputClass('email')}
            />
          </Field>
          <Field label="Password" error={fieldErrors.password}>
            <input
              type="password"
              autoComplete={isLogin ? 'current-password' : 'new-password'}
              value={values.password}
              onChange={update('password')}
              className={inputClass('password')}
            />
          </Field>
          {!isLogin && (
            <Field label="Confirm password" error={fieldErrors.confirm}>
              <input
                type="password"
                autoComplete="new-password"
                value={values.confirm}
                onChange={update('confirm')}
                className={inputClass('confirm')}
              />
            </Field>
          )}

          {error && (
            <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting && <Loader2 size={16} className="animate-spin" />}
            {submitting ? 'Please wait...' : isLogin ? 'Log in' : 'Sign up'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          {isLogin ? 'New here? ' : 'Already have an account? '}
          <Link to={isLogin ? '/signup' : '/login'} className="font-medium text-indigo-600 hover:underline">
            {isLogin ? 'Create an account' : 'Log in'}
          </Link>
        </p>
      </div>
      <Disclaimer className="mt-6" />
    </div>
  )
}
