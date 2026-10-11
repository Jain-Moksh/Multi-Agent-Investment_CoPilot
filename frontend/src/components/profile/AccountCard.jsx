import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import Button from '../Button'
import Card from '../Card'
import { useAuth } from '../../context/AuthContext'
import { formatDate } from '../../utils/format'

export default function AccountCard() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [loggingOut, setLoggingOut] = useState(false)

  async function handleLogout() {
    setLoggingOut(true)
    try {
      await logout()
    } finally {
      navigate('/login', { replace: true })
    }
  }

  return (
    <Card title="Account">
      <div className="space-y-1 text-sm">
        <p className="text-slate-500">Email</p>
        <p className="break-all font-medium text-slate-900">{user?.email || '-'}</p>
        <p className="pt-2 text-slate-500">Member since</p>
        <p className="font-medium text-slate-900">{formatDate(user?.created_at)}</p>
      </div>
      <Button variant="secondary" icon={LogOut} onClick={handleLogout} loading={loggingOut} className="mt-4 w-full">
        Log out
      </Button>
    </Card>
  )
}
