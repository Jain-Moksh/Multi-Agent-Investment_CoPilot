import Card from '../components/Card'
import ErrorBanner from '../components/ErrorBanner'
import PageHeader from '../components/PageHeader'
import Spinner from '../components/Spinner'
import AccountCard from '../components/profile/AccountCard'
import HowUsedCard from '../components/profile/HowUsedCard'
import LearnedProfileCard from '../components/profile/LearnedProfileCard'
import PreferencesForm from '../components/profile/PreferencesForm'
import useApi from '../hooks/useApi'
import { getProfile } from '../api/profile'

export default function Profile() {
  const profile = useApi(getProfile)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Profile"
        subtitle="Tell the copilot how you invest, and see what it has learned from your trades."
      />

      {profile.loading ? (
        <Card>
          <Spinner label="Loading your profile" />
        </Card>
      ) : profile.error ? (
        <ErrorBanner message={profile.error.message} onRetry={() => profile.reload()} />
      ) : (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          <div className="space-y-6 xl:col-span-2">
            <PreferencesForm profile={profile.data} onSaved={profile.setData} />
            <LearnedProfileCard profile={profile.data} />
          </div>
          <div className="space-y-6">
            <AccountCard />
            <HowUsedCard />
          </div>
        </div>
      )}
    </div>
  )
}
