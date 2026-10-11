import { Hammer } from 'lucide-react'
import EmptyState from '../../components/EmptyState'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'

export default function CardState({ request, loadingLabel = 'Loading', children }) {
  if (request.loading && !request.data) return <Spinner label={loadingLabel} />
  if (request.notBuilt) {
    return <EmptyState icon={Hammer} title="Not built yet" message="This part of the backend is not available yet." />
  }
  if (request.error) return <ErrorBanner message={request.error} onRetry={request.reload} />
  if (!request.data) return null
  return children(request.data)
}
