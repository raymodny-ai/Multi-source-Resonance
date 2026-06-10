import { useState } from 'react'
import { useAlerts, useAcknowledgeAlert } from '../api/alerts'
import { useIncidents, useIncidentDetail } from '../api/incidents'
import { useNotificationStatus, useNotificationConfig, useTestNotification, useUpdateNotificationConfig } from '../api/notifications'
import { useTimezoneStore } from '../stores/timezoneStore'
import { formatDateTime, formatRelativeTime } from '../utils/time'
import { ALERT_LEVEL_COLORS, ALERT_LEVEL_LABELS } from '../types/common'
import type { AlertLevel } from '../types/common'
import { ChevronDown, ChevronRight, RefreshCw, Zap } from 'lucide-react'

export default function AlertCenter() {
  const [viewMode, setViewMode] = useState<'incidents' | 'alerts'>('incidents')
  const [page, setPage] = useState(1)
  const [levelFilter, setLevelFilter] = useState('ALL')
  const [ackFilter, setAckFilter] = useState<string>('all')
  const [expandedIncident, setExpandedIncident] = useState<number | null>(null)
  const [cooldownVal, setCooldownVal] = useState(30)
  const [dndEnabled, setDndEnabled] = useState(false)
  const [cooldownSaved, setCooldownSaved] = useState(false)
  const [testingChannel, setTestingChannel] = useState<string | null>(null)
  const timezone = useTimezoneStore((s) => s.timezone)

  // Alerts (table view)
  const acknowledged = ackFilter === 'all' ? undefined : ackFilter === 'yes'
  const { data: alertsData, isLoading: alertsLoading } = useAlerts(page, 20, levelFilter === 'ALL' ? undefined : levelFilter, acknowledged)
  const acknowledge = useAcknowledgeAlert()

  // Incidents
  const { data: incidentsData } = useIncidents(7)
  const { data: incidentDetail } = useIncidentDetail(expandedIncident)

  // Notifications
  const { data: notifStatus } = useNotificationStatus()
  const { data: notifConfig } = useNotificationConfig()
  const testMutation = useTestNotification()
  const updateNotifConfig = useUpdateNotificationConfig()

  const alerts = alertsData?.data ?? []
  const total = alertsData?.total ?? 0
  const totalPages = Math.ceil(total / 20)
  const incidents = incidentsData?.incidents ?? []

  const handleTestChannel = async (channel: string) => {
    setTestingChannel(channel)
    try {
      await testMutation.mutateAsync(channel)
    } finally {
      setTestingChannel(null)
    }
  }

  const handleSaveCooldown = () => {
    updateNotifConfig.mutate({ cooldown_minutes: cooldownVal })
    setCooldownSaved(true)
    setTimeout(() => setCooldownSaved(false), 3000)
  }

  return (
    <div className="space-y-4 max-w-[1600px]">
      <h1 className="text-xl font-bold">告警通知中心</h1>

      {/* View mode toggle */}
      <div className="flex items-center gap-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-0.5 w-fit">
        {[
          { mode: 'incidents' as const, label: 'Incident 聚合' },
          { mode: 'alerts' as const, label: '告警列表' },
        ].map((m) => (
          <button
            key={m.mode}
            onClick={() => { setViewMode(m.mode); setPage(1) }}
            className={`px-4 py-1.5 text-xs rounded-md transition-colors ${viewMode === m.mode ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Filters (alerts view) */}
      {viewMode === 'alerts' && (
        <div className="flex flex-wrap items-center gap-3 p-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl">
          <div className="flex gap-1 flex-wrap">
            {['ALL', 'LEVEL_1', 'LEVEL_2', 'LEVEL_3'].map((lvl) => (
              <button
                key={lvl}
                onClick={() => { setLevelFilter(lvl); setPage(1) }}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${levelFilter === lvl ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
              >
                {lvl === 'ALL' ? '全部等级' : ALERT_LEVEL_LABELS[lvl as AlertLevel]}
              </button>
            ))}
          </div>
          <div className="border-l border-[var(--border)] h-5 hidden sm:block" />
          <div className="flex gap-1">
            {[{ value: 'all', label: '全部' }, { value: 'no', label: '未确认' }, { value: 'yes', label: '已确认' }].map((opt) => (
              <button
                key={opt.value}
                onClick={() => { setAckFilter(opt.value); setPage(1) }}
                className={`px-2 py-1 text-xs rounded-md transition-colors ${ackFilter === opt.value ? 'bg-[var(--border)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Incident List */}
      {viewMode === 'incidents' && (
        <div className="space-y-2">
          {incidents.length === 0 ? (
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-8 text-center">
              <p className="text-xs text-[var(--text-secondary)]">暂无活跃 Incident</p>
            </div>
          ) : (
            incidents.map((inc) => {
              const isExpanded = expandedIncident === inc.id
              const triggers = isExpanded && incidentDetail?.id === inc.id ? incidentDetail.triggers : []
              const durationMs = new Date(inc.end_time ?? Date.now()).getTime() - new Date(inc.start_time).getTime()
              const durationH = Math.floor(durationMs / 3600000)
              const durationM = Math.floor((durationMs % 3600000) / 60000)

              return (
                <div key={inc.id} className={`bg-[var(--bg-card)] border rounded-xl overflow-hidden transition-all ${inc.highest_level === 'LEVEL_3' ? 'border-[var(--accent-red)]/40' : 'border-[var(--border)]'}`}>
                  {/* Incident Header */}
                  <button
                    onClick={() => setExpandedIncident(isExpanded ? null : inc.id)}
                    className="w-full flex items-center gap-3 p-4 text-left hover:bg-white/5 transition-colors"
                  >
                    {isExpanded ? <ChevronDown size={16} className="text-[var(--text-secondary)]" /> : <ChevronRight size={16} className="text-[var(--text-secondary)]" />}
                    {!inc.reviewed && <span className="w-2 h-2 rounded-full bg-[var(--accent-red)] animate-pulse shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-[var(--text-primary)]">INCIDENT #{inc.id}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded text-white" style={{ backgroundColor: ALERT_LEVEL_COLORS[inc.highest_level] }}>
                          {ALERT_LEVEL_LABELS[inc.highest_level]}
                        </span>
                        <span className="text-[10px] text-[var(--text-secondary)]">{inc.title}</span>
                      </div>
                      <p className="text-[10px] text-[var(--text-secondary)] mt-1">
                        持续 {durationH}h{durationM}m · 最高 {inc.highest_score.toFixed(1)}/5.0 · {inc.trigger_count} 次触发
                        {inc.reviewed ? ' · ✅ 已复盘' : ' · ⬜ 未复盘'}
                      </p>
                    </div>
                    <span className="text-[10px] text-[var(--text-secondary)]">{formatRelativeTime(inc.start_time)}</span>
                  </button>

                  {/* Expanded triggers */}
                  {isExpanded && triggers.length > 0 && (
                    <div className="border-t border-[var(--border)] px-4 py-2 bg-[var(--bg-primary)]/30">
                      <p className="text-[10px] text-[var(--text-secondary)] mb-2">子触发明细 ({triggers.length}次)</p>
                      <div className="space-y-1">
                        {triggers.map((t) => (
                          <div key={t.id} className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]">
                            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: ALERT_LEVEL_COLORS[t.alert_level] }} />
                            <span>{formatDateTime(t.trigger_time, timezone)}</span>
                            <span className="font-medium text-[var(--text-primary)]">{t.alert_level.replace('LEVEL_', 'L')} {t.total_score.toFixed(1)}</span>
                            <span>{t.dimension_names.join('+')}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      )}

      {/* Alerts Table */}
      {viewMode === 'alerts' && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
          {alertsLoading ? (
            <div className="p-6 text-center text-[var(--text-secondary)] text-xs">加载中...</div>
          ) : alerts.length === 0 ? (
            <div className="p-6 text-center text-[var(--text-secondary)] text-xs">暂无告警记录</div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                      <th className="text-left px-4 py-3 font-medium">时间</th>
                      <th className="text-left px-4 py-3 font-medium">等级</th>
                      <th className="text-left px-4 py-3 font-medium">得分</th>
                      <th className="text-left px-4 py-3 font-medium hidden md:table-cell">维度</th>
                      <th className="text-left px-4 py-3 font-medium hidden lg:table-cell">Hawkes</th>
                      <th className="text-left px-4 py-3 font-medium">状态</th>
                      <th className="text-right px-4 py-3 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.map((alert) => (
                      <tr key={alert.id} className="border-b border-[var(--border)]/50 hover:bg-white/5">
                        <td className="px-4 py-2.5 text-[var(--text-primary)]">{formatDateTime(alert.trigger_time, timezone)}</td>
                        <td className="px-4 py-2.5">
                          <span className="inline-block px-1.5 py-0.5 rounded text-white" style={{ backgroundColor: ALERT_LEVEL_COLORS[alert.alert_level] }}>
                            {ALERT_LEVEL_LABELS[alert.alert_level]}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-[var(--text-primary)]">{alert.total_score.toFixed(1)}/5.0</td>
                        <td className="px-4 py-2.5 hidden md:table-cell text-[var(--text-secondary)]">
                          {Object.entries(alert.dimension_scores).filter(([, v]) => v > 0).map(([k]) => k).join('+') || '--'}
                        </td>
                        <td className="px-4 py-2.5 hidden lg:table-cell text-[var(--text-secondary)]">{alert.hawkes_branching_ratio.toFixed(2)}</td>
                        <td className="px-4 py-2.5">
                          {alert.acknowledged ? <span className="text-[var(--accent-green)]">✅ 已确认</span> : <span className="text-[var(--text-secondary)]">⬜ 未确认</span>}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          {!alert.acknowledged && (
                            <button onClick={() => acknowledge.mutate(alert.id)} className="text-[var(--accent-blue)] hover:underline text-xs">标记确认</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Pagination */}
              <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)]">
                <span className="text-xs text-[var(--text-secondary)]">共 {total} 条</span>
                <div className="flex gap-1">
                  {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => (
                    <button key={i + 1} onClick={() => setPage(i + 1)}
                      className={`w-7 h-7 text-xs rounded-md transition-colors ${i + 1 === page ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}>
                      {i + 1}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Notification Channels & Cooldown Config */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Channel Status */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">通知渠道连通性</h3>
          <div className="space-y-2">
            {(notifStatus?.channels ?? [
              { name: 'Email', connected: true, last_test: new Date().toISOString() },
              { name: 'Telegram', connected: true, last_test: new Date().toISOString() },
              { name: 'Discord', connected: false, last_test: null },
            ]).map((ch) => (
              <div key={ch.name} className="flex items-center justify-between py-2 px-3 rounded-lg bg-[var(--bg-primary)]/50">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${ch.connected ? 'bg-[var(--accent-green)]' : 'bg-[var(--accent-red)]'}`} />
                  <span className="text-xs text-[var(--text-primary)]">{ch.name}</span>
                  <span className={`text-[10px] ${ch.connected ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>
                    {ch.connected ? '✅ 正常' : '⚠️ 未配置'}
                  </span>
                </div>
                <button
                  onClick={() => handleTestChannel(ch.name.toLowerCase())}
                  disabled={!ch.connected || testingChannel === ch.name.toLowerCase()}
                  className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md border border-[var(--border)] text-[var(--text-secondary)] hover:text-white hover:border-white/30 disabled:opacity-50 transition-colors"
                >
                  <Zap size={10} />
                  {testingChannel === ch.name.toLowerCase() ? '发送中...' : '测试'}
                </button>
              </div>
            ))}
          </div>
          {testMutation.isSuccess && (
            <p className="text-[10px] text-[var(--accent-green)] mt-2">✅ 测试消息已发送</p>
          )}
        </div>

        {/* Cooldown / DND Config */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">免打扰/冷却期配置</h3>
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-[var(--text-secondary)]">冷却期（分钟）</span>
                <span className="text-xs text-[var(--text-primary)] font-mono">{cooldownVal} 分钟</span>
              </div>
              <input
                type="range"
                min={5}
                max={120}
                step={5}
                value={cooldownVal}
                onChange={(e) => setCooldownVal(Number(e.target.value))}
                className="w-full h-1.5 rounded-full bg-[var(--bg-primary)] cursor-pointer accent-[var(--accent-blue)]"
              />
              <div className="flex justify-between text-[9px] text-[var(--text-secondary)]">
                <span>5分钟</span>
                <span>120分钟</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">免打扰时段</span>
              <button
                onClick={() => setDndEnabled(!dndEnabled)}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${dndEnabled ? 'bg-[var(--accent-yellow)]/20 text-[var(--accent-yellow)]' : 'bg-[var(--border)]/30 text-[var(--text-secondary)]'}`}
              >
                {dndEnabled ? '已启用' : '不启用'}
              </button>
            </div>
            {dndEnabled && (
              <div className="flex items-center gap-2">
                <input type="time" defaultValue="22:00" className="px-2 py-1 rounded bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]" />
                <span className="text-xs text-[var(--text-secondary)]">至</span>
                <input type="time" defaultValue="08:00" className="px-2 py-1 rounded bg-[var(--bg-primary)] border border-[var(--border)] text-xs text-[var(--text-primary)]" />
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-xs text-[var(--text-secondary)]">同 Level 最小间隔</span>
              <span className="text-xs text-[var(--text-primary)]">15 分钟</span>
            </div>
            <button
              onClick={handleSaveCooldown}
              className="w-full py-2 rounded-lg bg-[var(--accent-blue)] text-white text-xs hover:opacity-90 transition-opacity"
            >
              {cooldownSaved ? '配置已保存 ✓' : '保存配置'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
