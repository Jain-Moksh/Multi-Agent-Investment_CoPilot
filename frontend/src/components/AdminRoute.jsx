import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { isSuperAdmin } from '../utils/admin'

export default function AdminRoute() {
  const { user } = useAuth()
  if (!isSuperAdmin(user)) return <Navigate to="/" replace />
  return <Outlet />
}
