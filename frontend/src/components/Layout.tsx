import { useState } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { useTimezoneStore } from '../stores/timezoneStore'
import { TIMEZONE_OPTIONS } from '../types/common'
import { formatTime, getCurrentDateStr } from '../utils/time'
import type { TimezoneOption } from '../types/common'
import {
  LayoutDashboard,
  ChartArea,
  Activity,
  Bell,
  Brain,
  Monitor,
  Settings,
  Menu,
  X,
  Clock,
} from 'lucide-react'

const NAV_ITEMS = [
  { path: '/', label: '仪表盘', icon: LayoutDashboard },
  { path: '/darkpool', label: '暗盘详情', icon: ChartArea },
  { path: '/signals', label: '共振信号', icon: Activity },
  { path: '/alerts', label: '告警中心', icon: Bell },
  { path: '/llm', label: 'LLM 分析', icon: Brain },
  { path: '/system', label: '系统状态', icon: Monitor },
  { path: '/config', label: '参数配置', icon: Settings },
]

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [timezoneMenuOpen, setTimezoneMenuOpen] = useState(false)
  const timezone = useTimezoneStore((s) => s.timezone)
  const setTimezone = useTimezoneStore((s) => s.setTimezone)

  const handleTimezoneChange = (tz: TimezoneOption) => {
    setTimezone(tz)
    setTimezoneMenuOpen(false)
  }

  const currentTzLabel =
    TIMEZONE_OPTIONS.find((o) => o.value === timezone)?.label ?? 'EST/EDT'

  return (
    <div className="flex h-screen bg-[var(--bg-primary)] text-[var(--text-primary)]">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 w-56 bg-[var(--bg-card)] border-r border-[var(--border)]
          transform transition-transform duration-200 lg:relative lg:translate-x-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
          flex flex-col
        `}
      >
        {/* Logo */}
        <div className="flex items-center justify-between h-14 px-4 border-b border-[var(--border)]">
          <span className="text-sm font-bold text-[var(--accent-blue)]">
            Multi-source Resonance
          </span>
          <button
            className="lg:hidden text-[var(--text-secondary)] hover:text-white"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 overflow-y-auto py-2">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg text-sm transition-colors
                ${
                  isActive
                    ? 'bg-[var(--accent-blue)]/15 text-[var(--accent-blue)]'
                    : 'text-[var(--text-secondary)] hover:text-white hover:bg-white/5'
                }`
              }
            >
              <item.icon size={18} />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="flex items-center justify-between h-14 px-4 border-b border-[var(--border)] bg-[var(--bg-card)] shrink-0">
          <button
            className="lg:hidden text-[var(--text-secondary)] hover:text-white"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu size={20} />
          </button>

          <div className="flex items-center gap-4 ml-auto">
            {/* Staleness indicator placeholder */}
            <span className="flex items-center gap-1.5 text-xs text-[var(--accent-green)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
              LIVE
            </span>

            {/* Clock */}
            <span className="text-xs text-[var(--text-secondary)] hidden sm:block">
              {getCurrentDateStr(timezone)}{' '}
              {formatTime(new Date().toISOString(), timezone)}
            </span>

            {/* Timezone switcher */}
            <div className="relative">
              <button
                onClick={() => setTimezoneMenuOpen(!timezoneMenuOpen)}
                className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-[var(--border)] text-[var(--text-secondary)] hover:text-white hover:border-[var(--text-secondary)] transition-colors"
              >
                <Clock size={14} />
                {currentTzLabel}
              </button>
              {timezoneMenuOpen && (
                <div className="absolute right-0 top-full mt-1 w-44 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg shadow-xl z-50">
                  {TIMEZONE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => handleTimezoneChange(opt.value)}
                      className={`w-full text-left px-3 py-2 text-xs hover:bg-white/5 transition-colors
                        ${opt.value === timezone ? 'text-[var(--accent-blue)]' : 'text-[var(--text-secondary)]'}
                      `}
                    >
                      {opt.label}
                      {opt.value === timezone && ' ✓'}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
