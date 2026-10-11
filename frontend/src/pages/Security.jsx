import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Activity, FileWarning, FlaskConical, LayoutGrid, Lock } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import OverviewTab from '../components/security/OverviewTab'
import AttackTesterTab from '../components/security/AttackTesterTab'
import EventsTab from '../components/security/EventsTab'
import QuarantineTab from '../components/security/QuarantineTab'
import PermissionsTab from '../components/security/PermissionsTab'

const TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutGrid, component: OverviewTab },
  { id: 'tester', label: 'Live Attack Tester', icon: FlaskConical, component: AttackTesterTab },
  { id: 'events', label: 'Events', icon: Activity, component: EventsTab },
  { id: 'quarantine', label: 'Quarantine', icon: FileWarning, component: QuarantineTab },
  { id: 'permissions', label: 'Agent Permissions', icon: Lock, component: PermissionsTab },
]

export default function Security() {
  const [searchParams, setSearchParams] = useSearchParams()
  const active = TABS.find((tab) => tab.id === searchParams.get('tab')) || TABS[0]
  const ActiveTab = active.component
  const activeRef = useRef(null)

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [active.id])

  return (
    <div>
      <PageHeader
        title="Security Center"
        subtitle="Two defence layers protect the AI: prompt injection and agent hijacking defence, and RAG poisoning detection."
      />

      <div className="mb-6 overflow-x-auto border-b border-slate-200">
        <nav className="flex min-w-max gap-1" role="tablist">
          {TABS.map(({ id, label, icon: Icon }) => {
            const selected = id === active.id
            return (
              <button
                key={id}
                ref={selected ? activeRef : null}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setSearchParams(id === TABS[0].id ? {} : { tab: id })}
                className={`-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition ${
                  selected
                    ? 'border-indigo-600 text-indigo-700'
                    : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800'
                }`}
              >
                <Icon size={16} />
                {label}
              </button>
            )
          })}
        </nav>
      </div>

      <ActiveTab />
    </div>
  )
}
