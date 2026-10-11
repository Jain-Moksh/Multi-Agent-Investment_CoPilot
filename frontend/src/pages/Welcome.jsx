import { useNavigate } from 'react-router-dom'
import { TrendingUp } from 'lucide-react'
import Card from '../components/Card'
import Disclaimer from '../components/Disclaimer'
import ErrorBanner from '../components/ErrorBanner'
import Spinner from '../components/Spinner'
import PreferencesForm from '../components/profile/PreferencesForm'
import useApi from '../hooks/useApi'
import { getProfile } from '../api/profile'

export default function Welcome() {
  const navigate = useNavigate()
  const profile = useApi(getProfile)
  const goToDashboard = () => navigate('/', { replace: true })

  return (
    <div className="flex min-h-screen flex-col items-center px-4 py-10">
      <div className="w-full max-w-4xl">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 text-white">
            <TrendingUp size={26} />
          </div>
          <h1 className="mt-3 text-2xl font-semibold text-slate-900">Welcome to Investment Copilot</h1>
          <p className="mt-1 max-w-xl text-sm text-slate-500">
            Tell us a little about how you invest so the analysis fits you from the very first recommendation. You can
            change these answers any time on the Profile page.
          </p>
        </div>

        {profile.loading ? (
          <Card>
            <Spinner label="Loading" />
          </Card>
        ) : profile.error ? (
          <ErrorBanner message={profile.error.message} onRetry={() => profile.reload()} />
        ) : (
          <PreferencesForm
            profile={profile.data}
            onSaved={goToDashboard}
            title="Your investing preferences"
            submitLabel="Save and continue"
            successMessage="Preferences saved. Welcome aboard!"
            note="All questions are optional."
            onSkip={goToDashboard}
          />
        )}
      </div>
      <Disclaimer className="mt-6" />
    </div>
  )
}
