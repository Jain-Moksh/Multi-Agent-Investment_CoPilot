import { Navigate } from 'react-router-dom'
import AuthForm from '../components/AuthForm'
import Spinner from '../components/Spinner'
import { useAuth } from '../context/AuthContext'

export default function Signup() {
  const { user, loading } = useAuth()
  if (loading) return <Spinner label="Restoring your session" />
  if (user) return <Navigate to="/" replace />
  return <AuthForm mode="signup" />
}
