import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import AdminRoute from './components/AdminRoute'
import Layout from './components/Layout'
import Spinner from './components/Spinner'
import { ToastProvider } from './components/Toast'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Welcome from './pages/Welcome'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Insights = lazy(() => import('./pages/Insights'))
const News = lazy(() => import('./pages/News'))
const Assistant = lazy(() => import('./pages/Assistant'))
const Opportunities = lazy(() => import('./pages/Opportunities'))
const Notifications = lazy(() => import('./pages/Notifications'))
const Profile = lazy(() => import('./pages/Profile'))
const Security = lazy(() => import('./pages/Security'))
const System = lazy(() => import('./pages/System'))

function page(Component) {
  return (
    <Suspense fallback={<Spinner label="Loading page" />}>
      <Component />
    </Suspense>
  )
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/welcome" element={<Welcome />} />
              <Route element={<Layout />}>
                <Route path="/" element={page(Dashboard)} />
                <Route path="/portfolio" element={page(Portfolio)} />
                <Route path="/insights" element={page(Insights)} />
                <Route path="/news" element={page(News)} />
                <Route path="/assistant" element={page(Assistant)} />
                <Route path="/opportunities" element={page(Opportunities)} />
                <Route path="/notifications" element={page(Notifications)} />
                <Route path="/profile" element={page(Profile)} />
                <Route element={<AdminRoute />}>
                  <Route path="/security" element={page(Security)} />
                  <Route path="/system" element={page(System)} />
                </Route>
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
