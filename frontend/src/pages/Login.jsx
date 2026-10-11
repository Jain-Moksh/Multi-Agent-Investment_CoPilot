import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import AuthForm from '../components/AuthForm'
import Spinner from '../components/Spinner'
import { useAuth } from '../context/AuthContext'
import { safeNextPath } from '../api/client'

export default function Login() {
  const { user, loading } = useAuth()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  if (loading) return <Spinner label="Restoring your session" />
  if (user) return <Navigate to={safeNextPath(searchParams.get('next') || location.state?.from)} replace />
  return <AuthForm mode="login" />
}
