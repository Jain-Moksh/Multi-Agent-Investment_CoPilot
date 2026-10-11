import { Hammer } from 'lucide-react'
import Card from './Card'
import EmptyState from './EmptyState'

export default function PagePlaceholder({ title }) {
  return (
    <Card>
      <EmptyState icon={Hammer} title={title} message="This page is coming soon." />
    </Card>
  )
}
