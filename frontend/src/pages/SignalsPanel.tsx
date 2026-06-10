import { useState } from 'react'
import { useDashboardScores } from '../api/dashboard'
import { useSignalHistory, useAcknowledgeSignal } from '../api/signals'
import { useTimezoneStore } from '../stores/timezoneStore'
import { formatTime, formatRelativeTime } from '../utils/time'
import { ALERT_LEVEL_COLORS, ALERT_LEVEL_LABELS, STATE_COLORS } from '../types/common'
import type { SignalRecord } from '../types/api'
import type { AlertLevel } from '../types/common'

type RangeDays = 7 | 30 | 90

export default function SignalsPanel() {
  const [range, setRange] = useState<RangeDays>(30)
  const [selectedSignal, setSelectedSignal] = useState<SignalRecord | null>(null)
  const timezone = useTimezoneStore((s) => s.timezone)

  const { data: scores, isLoading } = useDashboardScores()
  const { data: historyData } = useSignalHistory(range)
  const acknowledge = useAcknowledgeSignal()

  if (isLoading || !scores) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">共振信号面板</h1>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="h-64 rounded-xl skeleton" />
          <div className="h-64 rounded-xl skeleton" />
        </div>
      </div>
    )
  }

  const { dimensions, resonance, hawkes } = scores
  const { gex, vix, crypto, darkpool } = dimensions

  // Condition items
  const conditions = [
    { label: 'GEX', active: gex.score > 0, details: gex.details },
    { label: 'VIX', active: vix.score > 0, details: vix.details },
    { label: 'CRYPTO', active: crypto.score > 0, details: crypto.details },
    { label: 'DARKPOOL', active: darkpool.score > 0, details: darkpool.details },
    { label: 'Hawkes', active: hawkes.branching_ratio < 0.7, details: hawkes.details },
  ]

  const ringSegments = [
    { name: 'GEX', value: gex.score, max: 1.5, color: STATE_COLORS[gex.state] ?? '#64748b' },
    { name: 'VIX', value: vix.score, max: 1.0, color: STATE_COLORS[vix.state] ?? '#64748b' },
    { name: 'Crypto', value: crypto.score, max: 1.0, color: STATE_COLORS[crypto.state] ?? '#64748b' },
    { name: 'Darkpool', value: darkpool.score, max: 1.5, color: STATE_COLORS[darkpool.state] ?? '#64748b' },
  ]

  // Calculate ring arc parameters
  const totalMax = 5.0
  const ringRadius = 60
  const ringStroke = 12
  const circumference = 2 * Math.PI * ringRadius
  let accumulatedAngle = -90 // Start from top

  const arcs = ringSegments.map((seg) => {
    const segmentAngle = (seg.max / totalMax) * 360
    const dashLength = (seg.value / seg.max) * (segmentAngle / 360) * circumference
    const startAngle = accumulatedAngle
    accumulatedAngle += segmentAngle
    return {
      ...seg,
      dashLength: Math.max(dashLength, 0.5),
      startAngle,
      segmentAngle,
    }
  })

  const history = historyData?.data ?? []

  return (
    <div className="space-y-4 max-w-[1600px]">
      <h1 className="text-xl font-bold">共振信号面板</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Current resonance ring */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6 flex flex-col items-center">
          <h3 className="text-sm font-semibold mb-4 self-start">当前共振状态</h3>
          <div className="relative w-48 h-48">
            <svg viewBox="0 0 160 160" className="w-full h-full -rotate-90">
              {/* Background rings */}
              {ringSegments.map((seg, i) => {
                const innerR = ringRadius - ringStroke / 2
                const outerR = ringRadius + ringStroke / 2
                return (
                  <circle
                    key={`bg-${i}`}
                    cx="80" cy="80" r={ringRadius}
                    fill="none"
                    stroke="var(--border)"
                    strokeWidth={ringStroke}
                    strokeDasharray={`${(seg.max / totalMax) * circumference} ${circumference * (1 - seg.max / totalMax)}`}
                    strokeDashoffset={-(arcs[i].startAngle / 360) * circumference}
                  />
                )
              })}
              {/* Filled arcs */}
              {arcs.map((arc, i) => (
                <circle
                  key={`fill-${i}`}
                  cx="80" cy="80" r={ringRadius}
                  fill="none"
                  stroke={arc.color}
                  strokeWidth={ringStroke}
                  strokeLinecap="round"
                  strokeDasharray={`${arc.dashLength} ${circumference - arc.dashLength}`}
                  strokeDashoffset={-(arc.startAngle / 360) * circumference}
                  className="transition-all duration-700"
                />
              ))}
            </svg>
            {/* Center text */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span
                className="text-3xl font-bold"
                style={{ color: ALERT_LEVEL_COLORS[resonance.alert_level] }}
              >
                {resonance.total_score.toFixed(1)}
              </span>
              <span className="text-xs text-[var(--text-secondary)]">/ {resonance.max_score.toFixed(1)}</span>
              <span
                className="text-xs font-bold mt-1 px-2 py-0.5 rounded"
                style={{
                  backgroundColor: ALERT_LEVEL_COLORS[resonance.alert_level],
                  color: '#fff',
                }}
              >
                {ALERT_LEVEL_LABELS[resonance.alert_level]}
              </span>
            </div>
          </div>
          {/* Legend */}
          <div className="flex flex-wrap justify-center gap-3 mt-4 text-[10px]">
            {ringSegments.map((seg) => (
              <span key={seg.name} className="flex items-center gap-1 text-[var(--text-secondary)]">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: seg.color }} />
                {seg.name} ({seg.value}/{seg.max})
              </span>
            ))}
          </div>
          <p className="text-xs text-[var(--text-secondary)] mt-2">
            上次触发: {formatTime(scores.timestamp, timezone, 'HH:mm:ss')}
            {' '}({formatRelativeTime(scores.timestamp)})
          </p>
        </div>

        {/* Trigger conditions */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6">
          <h3 className="text-sm font-semibold mb-4">触发条件逐项点亮</h3>
          <div className="space-y-3">
            {conditions.map((cond) => (
              <div
                key={cond.label}
                className={`flex items-start gap-3 p-3 rounded-lg border transition-all ${
                  cond.active
                    ? 'border-[var(--accent-green)]/30 bg-[var(--accent-green)]/5'
                    : 'border-[var(--border)] bg-transparent'
                }`}
              >
                <span
                  className={`w-2.5 h-2.5 rounded-full mt-1 shrink-0 ${
                    cond.active ? 'bg-[var(--accent-green)]' : 'bg-[var(--text-secondary)]'
                  }`}
                />
                <div>
                  <p className={`text-xs font-medium ${cond.active ? 'text-[var(--accent-green)]' : 'text-[var(--text-secondary)]'}`}>
                    {cond.label}
                  </p>
                  <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">
                    {cond.active ? cond.details : '未触发'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Historical signal timeline */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">历史信号时间轴</h3>
          <div className="flex gap-1 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg p-0.5">
            {([7, 30, 90] as RangeDays[]).map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  r === range
                    ? 'bg-[var(--accent-blue)] text-white'
                    : 'text-[var(--text-secondary)] hover:text-white'
                }`}
              >
                {r}d
              </button>
            ))}
          </div>
        </div>

        {/* Timeline */}
        <div className="relative">
          {history.length === 0 ? (
            <p className="text-xs text-[var(--text-secondary)] py-8 text-center">暂无历史信号数据</p>
          ) : (
            <div className="space-y-1">
              {history.map((signal) => (
                <button
                  key={signal.id}
                  onClick={() => setSelectedSignal(signal)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors hover:bg-white/5 ${
                    selectedSignal?.id === signal.id ? 'bg-white/5 border border-[var(--border)]' : ''
                  }`}
                >
                  {/* Level dot */}
                  <span
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{
                      backgroundColor: ALERT_LEVEL_COLORS[signal.alert_level],
                      width: signal.total_score * 4 + 6,
                      height: signal.total_score * 4 + 6,
                    }}
                  />
                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-[var(--text-secondary)]">
                        {formatTime(signal.trigger_time, timezone, 'MM/DD HH:mm')}
                      </span>
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: ALERT_LEVEL_COLORS[signal.alert_level],
                          color: '#fff',
                        }}
                      >
                        {ALERT_LEVEL_LABELS[signal.alert_level]}
                      </span>
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                      {signal.total_score.toFixed(1)}/5.0
                      {' · '}
                      {Object.values(signal.dimension_scores).filter((s) => s > 0).length}/4 维度触发
                      {' · '}
                      Hawkes {signal.hawkes_branching_ratio.toFixed(2)}
                      {signal.acknowledged && ' · ✅ 已确认'}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Signal detail panel */}
        {selectedSignal && (
          <div className="mt-4 p-4 border border-[var(--border)] rounded-lg bg-[var(--bg-primary)]/50">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm font-semibold mb-2">
                  🚨 {ALERT_LEVEL_LABELS[selectedSignal.alert_level]} 共振信号触发
                </p>
                <p className="text-xs text-[var(--text-secondary)]">
                  ⏰ {formatTime(selectedSignal.trigger_time, timezone, 'YYYY-MM-DD HH:mm:ss')}
                </p>
                <p className="text-xs text-[var(--text-secondary)] mt-1">
                  📊 得分: {selectedSignal.total_score.toFixed(1)}/5.0
                  {' · '}
                  触发维度: {Object.values(selectedSignal.dimension_scores).filter((s) => s > 0).length}/4
                  {' · '}
                  Hawkes: {selectedSignal.hawkes_branching_ratio.toFixed(2)}
                </p>
              </div>
              <button
                onClick={() => acknowledge.mutate(selectedSignal.id)}
                disabled={selectedSignal.acknowledged || acknowledge.isPending}
                className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                  selectedSignal.acknowledged
                    ? 'bg-[var(--border)] text-[var(--text-secondary)] cursor-not-allowed'
                    : 'bg-[var(--accent-blue)] text-white hover:opacity-90'
                }`}
              >
                {selectedSignal.acknowledged ? '已确认' : acknowledge.isPending ? '确认中...' : '标记为已确认'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
