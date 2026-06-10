import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import DarkpoolDetail from './pages/DarkpoolDetail'
import SignalsPanel from './pages/SignalsPanel'
import AlertCenter from './pages/AlertCenter'
import SystemStatus from './pages/SystemStatus'
import ConfigPanel from './pages/ConfigPanel'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
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
