import { useState } from 'react'
import { useAlerts, useAcknowledgeAlert } from '../api/alerts'
import { useTimezoneStore } from '../stores/timezoneStore'
import { formatDateTime } from '../utils/time'
import { ALERT_LEVEL_COLORS, ALERT_LEVEL_LABELS } from '../types/common'
import type { AlertLevel } from '../types/common'

export default function AlertCenter() {
  const [page, setPage] = useState(1)
  const [levelFilter, setLevelFilter] = useState('ALL')
  const [ackFilter, setAckFilter] = useState<string>('all')
  const timezone = useTimezoneStore((s) => s.timezone)

  const acknowledged = ackFilter === 'all' ? undefined : ackFilter === 'yes'
  const { data, isLoading } = useAlerts(page, 20, levelFilter === 'ALL' ? undefined : levelFilter, acknowledged)
  const acknowledge = useAcknowledgeAlert()

  const alerts = data?.data ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / 20)

  return (
    <div className="space-y-4 max-w-[1600px]">
      <h1 className="text-xl font-bold">告警通知中心</h1>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 p-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl">
        <div className="flex gap-1">
          {['ALL', 'LEVEL_1', 'LEVEL_2', 'LEVEL_3'].map((lvl) => (
            <button
              key={lvl}
              onClick={() => { setLevelFilter(lvl); setPage(1) }}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                levelFilter === lvl
                  ? 'bg-[var(--accent-blue)] text-white'
                  : 'text-[var(--text-secondary)] hover:text-white'
              }`}
            >
              {lvl === 'ALL' ? '全部' : ALERT_LEVEL_LABELS[lvl as AlertLevel]}
            </button>
          ))}
        </div>
        <div className="border-l border-[var(--border)] h-5" />
        <div className="flex gap-1">
          {[
            { value: 'all', label: '全部状态' },
            { value: 'no', label: '未确认' },
            { value: 'yes', label: '已确认' },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => { setAckFilter(opt.value); setPage(1) }}
              className={`px-2 py-1 text-xs rounded-md transition-colors ${
                ackFilter === opt.value
                  ? 'bg-[var(--border)] text-white'
                  : 'text-[var(--text-secondary)] hover:text-white'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-6 text-center text-[var(--text-secondary)]">加载中...</div>
        ) : alerts.length === 0 ? (
          <div className="p-6 text-center text-[var(--text-secondary)]">暂无告警记录</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                    <th className="text-left px-4 py-3 font-medium">时间</th>
                    <th className="text-left px-4 py-3 font-medium">等级</th>
                    <th className="text-left px-4 py-3 font-medium">得分</th>
                    <th className="text-left px-4 py-3 font-medium hidden md:table-cell">触发维度</th>
                    <th className="text-left px-4 py-3 font-medium hidden lg:table-cell">Hawkes</th>
                    <th className="text-left px-4 py-3 font-medium">状态</th>
                    <th className="text-right px-4 py-3 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((alert) => (
                    <tr key={alert.id} className="border-b border-[var(--border)]/50 hover:bg-white/5">
                      <td className="px-4 py-2.5 text-[var(--text-primary)]">
                        {formatDateTime(alert.trigger_time, timezone)}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className="inline-block px-1.5 py-0.5 rounded text-white"
                          style={{ backgroundColor: ALERT_LEVEL_COLORS[alert.alert_level] }}
                        >
                          {ALERT_LEVEL_LABELS[alert.alert_level]}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-[var(--text-primary)]">
                        {alert.total_score.toFixed(1)}/5.0
                      </td>
                      <td className="px-4 py-2.5 hidden md:table-cell text-[var(--text-secondary)]">
                        {Object.entries(alert.dimension_scores)
                          .filter(([, v]) => v > 0)
                          .map(([k]) => k)
                          .join('+') || '--'}
                      </td>
                      <td className="px-4 py-2.5 hidden lg:table-cell text-[var(--text-secondary)]">
                        {alert.hawkes_branching_ratio.toFixed(2)}
                      </td>
                      <td className="px-4 py-2.5">
                        {alert.acknowledged ? (
                          <span className="text-[var(--accent-green)]">✅ 已确认</span>
                        ) : (
                          <span className="text-[var(--text-secondary)]">⬜ 未确认</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {!alert.acknowledged && (
                          <button
                            onClick={() => acknowledge.mutate(alert.id)}
                            className="text-[var(--accent-blue)] hover:underline text-xs"
                          >
                            标记已确认
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)]">
              <span className="text-xs text-[var(--text-secondary)]">
                共 {total} 条记录
              </span>
              <div className="flex gap-1">
                {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => {
                  const p = i + 1
                  return (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={`w-7 h-7 text-xs rounded-md transition-colors ${
                        p === page
                          ? 'bg-[var(--accent-blue)] text-white'
                          : 'text-[var(--text-secondary)] hover:text-white'
                      }`}
                    >
                      {p}
                    </button>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Notification channel status & Cooldown */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">通知渠道状态</h3>
          <div className="space-y-2 text-xs">
            {[
              { name: 'Email', status: '🟢 正常' },
              { name: 'Telegram', status: '🟢 正常' },
              { name: 'Discord', status: '🔴 未配置' },
            ].map((ch) => (
              <div key={ch.name} className="flex justify-between py-1 border-b border-[var(--border)]/50">
                <span className="text-[var(--text-primary)]">{ch.name}</span>
                <span>{ch.status}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">免打扰/冷却期配置</h3>
          <div className="space-y-3 text-xs text-[var(--text-secondary)]">
            <div className="flex items-center justify-between">
              <span>冷却期</span>
              <span className="text-[var(--text-primary)]">30 分钟</span>
            </div>
            <div className="flex items-center justify-between">
              <span>免打扰</span>
              <span className="text-[var(--text-primary)]">不启用</span>
            </div>
            <div className="flex items-center justify-between">
              <span>同一Level最小间隔</span>
              <span className="text-[var(--text-primary)]">15 分钟</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
