import { Hammer } from 'lucide-react'
import Card from '../Card'
import EmptyState from '../EmptyState'
import ErrorBanner from '../ErrorBanner'
import Spinner from '../Spinner'
import { isNotBuilt } from '../../api/client'

export default function AsyncBlock({ loading, error, onRetry, label = 'Loading', children }) {
  if (loading) return <Spinner label={label} />
  if (error && isNotBuilt(error.raw)) {
    return (
      <Card>
        <EmptyState icon={Hammer} title="Not built yet" message="This endpoint is not available on the backend." />
      </Card>
    )
  }
  if (error) return <ErrorBanner message={error.message} onRetry={onRetry} />
  return children
}
