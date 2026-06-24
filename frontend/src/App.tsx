import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import DarkpoolDetail from './pages/DarkpoolDetail'
import SignalsPanel from './pages/SignalsPanel'
import AlertCenter from './pages/AlertCenter'
import SystemStatus from './pages/SystemStatus'
import LLMAnalysis from './pages/LLMAnalysis'
import ConfigPanel from './pages/ConfigPanel'
const GammaDashboard = lazy(() => import('./pages/GammaDashboard'))

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="darkpool" element={<DarkpoolDetail />} />
          <Route path="signals" element={<SignalsPanel />} />
          <Route path="alerts" element={<AlertCenter />} />
          <Route path="llm" element={<LLMAnalysis />} />
          <Route path="system" element={<SystemStatus />} />
          <Route path="config" element={<ConfigPanel />} />
          <Route path="gex" element={
            <Suspense fallback={<div className="p-8 text-[var(--text-secondary)]">加载中...</div>}>
              <GammaDashboard />
            </Suspense>
          } />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
