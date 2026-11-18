import { createBrowserRouter, Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import AppLayout from '../layouts/AppLayout'
import Dashboard from '../pages/Dashboard'
import Articles from '../pages/Articles'
import Basecamp from '../pages/Basecamp'
import AIProcessor from '../pages/AIProcessor'
import EnvatoImages from '../pages/EnvatoImages'
import WordPress from '../pages/WordPress'
import Queue from '../pages/Queue'
import Settings from '../pages/Settings'
import Login from '../pages/Login'
import Reports from '../pages/Reports'
import AdminActivity from '../pages/AdminActivity'

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="animate-spin h-8 w-8 border-4 border-indigo-600 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return children
}

function AdminRoute({ children }) {
  const { isAuthenticated, isAdmin, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="animate-spin h-8 w-8 border-4 border-indigo-600 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (!isAdmin) {
    return <Navigate to="/" replace />
  }

  return children
}

const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/',
    element: <ProtectedRoute><AppLayout /></ProtectedRoute>,
    children: [
      { index: true,               element: <Dashboard /> },
      { path: 'reports',           element: <Reports /> },
      { path: 'admin/activity',    element: <AdminRoute><AdminActivity /></AdminRoute> },
      { path: 'articles',          element: <Articles /> },
      { path: 'basecamp',          element: <Basecamp /> },
      { path: 'ai-processor',      element: <AIProcessor /> },
      { path: 'envato-images',     element: <EnvatoImages /> },
      { path: 'wordpress',         element: <WordPress /> },
      { path: 'queue',             element: <Queue /> },
      { path: 'settings',          element: <Settings /> },
    ],
  },
])

export default router
