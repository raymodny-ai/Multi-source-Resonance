import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import Dashboard from './pages/Dashboard'
import DarkpoolDetail from './pages/DarkpoolDetail'
import SignalsPanel from './pages/SignalsPanel'
import AlertCenter from './pages/AlertCenter'
import SystemStatus from './pages/SystemStatus'
import ConfigPanel from './pages/ConfigPanel'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="darkpool" element={<DarkpoolDetail />} />
          <Route path="signals" element={<SignalsPanel />} />
          <Route path="alerts" element={<AlertCenter />} />
          <Route path="system" element={<SystemStatus />} />
          <Route path="config" element={<ConfigPanel />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
