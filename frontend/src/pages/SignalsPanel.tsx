import { useState, useMemo } from 'react'
import { useDashboardScores } from '../api/dashboard'
import { useSignalHistory, useAcknowledgeSignal } from '../api/signals'
import { useTimezoneStore } from '../stores/timezoneStore'
import { formatTime, formatRelativeTime } from '../utils/time'
import { ALERT_LEVEL_COLORS, ALERT_LEVEL_LABELS, HAWKES_STATE_COLORS, HAWKES_STATE_LABELS } from '../types/common'
import type { SignalRecord } from '../types/api'
import type { AlertLevel } from '../types/common'
import { X } from 'lucide-react'

type RangeDays = 7 | 30 | 90
type LevelFilter = 'ALL' | 'LEVEL_3' | 'LEVEL_2' | 'LEVEL_1'

export default function SignalsPanel() {
  const [range, setRange] = useState<RangeDays>(30)
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('ALL')
  const [selectedSignal, setSelectedSignal] = useState<SignalRecord | null>(null)
  const timezone = useTimezoneStore((s) => s.timezone)

  const { data: scores, isLoading } = useDashboardScores()
  const { data: historyData } = useSignalHistory(range)
  const acknowledge = useAcknowledgeSignal()

  const { dimensions, resonance, hawkes } = (scores ?? {}) as NonNullable<typeof scores>
  const gex = dimensions?.gex
  const vix = dimensions?.vix
  const crypto = dimensions?.crypto
  const darkpool = dimensions?.darkpool

  // Conditions
  const conditions = useMemo(() => {
    if (!gex || !vix || !crypto || !darkpool || !hawkes) return []
    return [
      { label: 'GEX 翻正', active: gex.score > 0, details: `GEX敞口 ${gex.state === 'FLIP_ON' ? '翻正 +$150M' : gex.details}`, color: '#22c55e' },
      { label: 'VIX Contango', active: vix.score > 0, details: `VIX ${vix.state} Ratio ${vix.term_structure_ratio.toFixed(2)}`, color: '#22c55e' },
      { label: 'CRYPTO 去杠杆', active: crypto.score > 0, details: crypto.leverage_cleanup_confirmed ? '去杠杆确认完成' : crypto.details, color: '#eab308' },
      { label: 'DARKPOOL 3/3', active: darkpool.score > 0, details: darkpool.state === 'TRIGGERED_3OF3' ? '三驾马车全部触发' : darkpool.details, color: '#a855f7' },
      { label: 'Hawkes 衰竭', active: hawkes.branching_ratio < 0.7, details: `分支比 ${hawkes.branching_ratio.toFixed(2)} ${HAWKES_STATE_LABELS[hawkes.state]}`, color: HAWKES_STATE_COLORS[hawkes.state] },
    ]
  }, [gex, vix, crypto, darkpool, hawkes])

  // Ring segments
  const ringSegments = useMemo(() => {
    if (!gex || !vix || !crypto || !darkpool) return []
    return [
      { name: 'GEX', value: gex.score, max: 1.5, color: '#22c55e' },
      { name: 'VIX', value: vix.score, max: 1.0, color: '#3b82f6' },
      { name: 'Crypto', value: crypto.score, max: 1.0, color: '#eab308' },
      { name: 'Darkpool', value: darkpool.score, max: 1.5, color: '#a855f7' },
    ]
  }, [gex, vix, crypto, darkpool])

  const totalMax = 5.0
  const ringRadius = 64
  const ringStroke = 14
  const ringGap = 3
  const circumference = 2 * Math.PI * ringRadius
  let accumulatedAngle = -90

  const arcs = ringSegments.map((seg) => {
    const segAngle = (seg.max / totalMax) * 360 - (ringGap * 2)
    const fillAngle = (seg.value / seg.max) * segAngle
    const dashLen = (fillAngle / 360) * circumference
    const startAngle = accumulatedAngle + ringGap
    accumulatedAngle = startAngle + segAngle + ringGap
    return { ...seg, dashLen: Math.max(dashLen, 0.3), startAngle, segAngle }
  })

  // Background arcs
  const bgArcs = ringSegments.map((seg, i) => {
    const segAngle = (seg.max / totalMax) * 360 - (ringGap * 2)
    const startAngle = -90 + i * (360 / 4) + ringGap
    return { ...seg, segAngle, startAngle, dashLen: (segAngle / 360) * circumference }
  })

  // Filter signals
  const allHistory = historyData?.data ?? []
  const filteredHistory = useMemo(() => {
    if (levelFilter === 'ALL') return allHistory
    return allHistory.filter((s) => s.alert_level === levelFilter)
  }, [allHistory, levelFilter])

  if (isLoading || !scores) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">共振信号面板</h1>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="h-80 rounded-xl skeleton" />
          <div className="h-80 rounded-xl skeleton" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 max-w-[1600px]">
      <h1 className="text-xl font-bold">共振信号面板</h1>

      {/* Ring + Conditions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Ring Chart */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6 flex flex-col items-center">
          <h3 className="text-sm font-semibold mb-4 self-start">当前共振状态</h3>
          <div className="relative w-52 h-52">
            <svg viewBox="0 0 180 180" className="w-full h-full -rotate-90">
              {/* Background arcs */}
              {bgArcs.map((seg, i) => (
                <circle key={`bg-${i}`} cx="90" cy="90" r={ringRadius} fill="none"
                  stroke="var(--border)" strokeWidth={ringStroke}
                  strokeDasharray={`${seg.dashLen} ${circumference - seg.dashLen}`}
                  strokeDashoffset={-(seg.startAngle / 360) * circumference}
                />
              ))}
              {/* Filled arcs */}
              {arcs.map((arc, i) => (
                <circle key={`fill-${i}`} cx="90" cy="90" r={ringRadius} fill="none"
                  stroke={arc.color} strokeWidth={ringStroke} strokeLinecap="round"
                  strokeDasharray={`${arc.dashLen} ${circumference - arc.dashLen}`}
                  strokeDashoffset={-(arc.startAngle / 360) * circumference}
                  className="transition-all duration-700"
                />
              ))}
            </svg>
            {/* Center */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-4xl font-bold" style={{ color: ALERT_LEVEL_COLORS[resonance.alert_level] }}>
                {resonance.total_score.toFixed(1)}
              </span>
              <span className="text-xs text-[var(--text-secondary)]">/ {resonance.max_score.toFixed(1)}</span>
              <span className="text-xs font-bold mt-1.5 px-2.5 py-0.5 rounded text-white"
                style={{ backgroundColor: ALERT_LEVEL_COLORS[resonance.alert_level] }}>
                {ALERT_LEVEL_LABELS[resonance.alert_level]}
              </span>
            </div>
          </div>
          {/* Ring Legend */}
          <div className="flex flex-wrap justify-center gap-3 mt-4 text-[10px]">
            {ringSegments.map((seg) => (
              <span key={seg.name} className="flex items-center gap-1 text-[var(--text-secondary)]">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: seg.color }} />
                {seg.name} <span className="text-[var(--text-primary)]">{seg.value}/{seg.max}</span>
              </span>
            ))}
          </div>
          <p className="text-xs text-[var(--text-secondary)] mt-2">
            上次触发: {formatTime(scores.timestamp, timezone, 'HH:mm:ss')} ({formatRelativeTime(scores.timestamp)})
          </p>
        </div>

        {/* Trigger Conditions */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6">
          <h3 className="text-sm font-semibold mb-4">触发条件逐项点亮</h3>
          <div className="space-y-3">
            {conditions.map((cond) => (
              <div
                key={cond.label}
                className={`flex items-start gap-3 p-3 rounded-lg border transition-all ${
                  cond.active ? 'border-[var(--accent-green)]/30 bg-[var(--accent-green)]/5' : 'border-[var(--border)]'
                }`}
              >
                <span className={`w-3 h-3 rounded-full mt-0.5 shrink-0 ${
                  cond.active ? 'bg-[var(--accent-green)] shadow-[0_0_6px_var(--accent-green)]' : 'bg-[var(--text-secondary)]'
                }`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className={`text-xs font-semibold ${cond.active ? 'text-[var(--accent-green)]' : 'text-[var(--text-secondary)]'}`}>
                      {cond.active ? '✅' : '⚫'} {cond.label}
                    </p>
                    {cond.active && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-[var(--accent-green)]/20 text-[var(--accent-green)]">
                        TRIGGERED
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-[var(--text-secondary)] mt-0.5">{cond.details}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Historical Timeline */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h3 className="text-sm font-semibold">历史信号时间轴</h3>
          <div className="flex items-center gap-2">
            {/* Level filter */}
            <div className="flex gap-1 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg p-0.5">
              {(['ALL', 'LEVEL_3', 'LEVEL_2', 'LEVEL_1'] as LevelFilter[]).map((lvl) => (
                <button
                  key={lvl}
                  onClick={() => setLevelFilter(lvl)}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    levelFilter === lvl ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'
                  }`}
                >
                  {lvl === 'ALL' ? '全部' : ALERT_LEVEL_LABELS[lvl as AlertLevel]}
                </button>
              ))}
            </div>
            {/* Range selector */}
            <div className="flex gap-1 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg p-0.5">
              {([7, 30, 90] as RangeDays[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={`px-2.5 py-1 text-xs rounded-md transition-colors ${r === range ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
                >
                  {r}d
                </button>
              ))}
            </div>
          </div>
        </div>

        {filteredHistory.length === 0 ? (
          <p className="text-xs text-[var(--text-secondary)] py-8 text-center">暂无历史信号数据</p>
        ) : (
          <div className="space-y-0.5">
            {filteredHistory.map((signal) => (
              <button
                key={signal.id}
                onClick={() => setSelectedSignal(signal)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors hover:bg-white/5 ${
                  selectedSignal?.id === signal.id ? 'bg-white/5 border border-[var(--border)]' : ''
                }`}
              >
                <span
                  className="rounded-full shrink-0"
                  style={{
                    backgroundColor: ALERT_LEVEL_COLORS[signal.alert_level],
                    width: Math.max(8, signal.total_score * 4 + 6),
                    height: Math.max(8, signal.total_score * 4 + 6),
                  }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-[var(--text-secondary)]">
                      {formatTime(signal.trigger_time, timezone, 'MM/DD HH:mm')}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded text-white"
                      style={{ backgroundColor: ALERT_LEVEL_COLORS[signal.alert_level] }}>
                      {ALERT_LEVEL_LABELS[signal.alert_level]}
                    </span>
                    {signal.trigger_count > 1 && (
                      <span className="text-[9px] text-[var(--text-secondary)]">×{signal.trigger_count}</span>
                    )}
                  </div>
                  <p className="text-[10px] text-[var(--text-secondary)] mt-0.5">
                    {signal.total_score.toFixed(1)}/5.0
                    {' · '}{Object.values(signal.dimension_scores).filter((s) => s > 0).length}/4 维度
                    {' · '}Hawkes {signal.hawkes_branching_ratio.toFixed(2)}
                    {signal.acknowledged && ' · ✅'}
                  </p>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Signal Detail Drawer */}
        {selectedSignal && (
          <div className="mt-4 p-4 border border-[var(--border)] rounded-lg bg-[var(--bg-primary)]/50">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm font-semibold mb-2" style={{ color: ALERT_LEVEL_COLORS[selectedSignal.alert_level] }}>
                  🚨 {ALERT_LEVEL_LABELS[selectedSignal.alert_level]} 共振信号触发
                </p>
                <p className="text-xs text-[var(--text-secondary)]">
                  ⏰ {formatTime(selectedSignal.trigger_time, timezone, 'YYYY-MM-DD HH:mm:ss')} EST
                  {` (${formatRelativeTime(selectedSignal.trigger_time)})`}
                </p>
                <div className="mt-2 space-y-1 text-[10px] text-[var(--text-secondary)]">
                  <p>📊 共振得分: {selectedSignal.total_score.toFixed(1)}/5.0 ({((selectedSignal.total_score / 5) * 100).toFixed(0)}%)</p>
                  <p>🔢 触发维度: {Object.entries(selectedSignal.dimension_scores).filter(([, v]) => v > 0).map(([k, v]) => `${k}=${v}`).join(', ') || '无'}</p>
                  <p>📐 Hawkes 分支比: {selectedSignal.hawkes_branching_ratio.toFixed(2)}</p>
                  <p>📋 触发次数: {selectedSignal.trigger_count} 次</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
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
                <button
                  onClick={() => setSelectedSignal(null)}
                  className="text-[var(--text-secondary)] hover:text-white transition-colors"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Score breakdown */}
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { label: 'GEX', score: selectedSignal.dimension_scores.gex ?? 0, max: 1.5 },
                { label: 'VIX', score: selectedSignal.dimension_scores.vix ?? 0, max: 1.0 },
                { label: 'Crypto', score: selectedSignal.dimension_scores.crypto ?? 0, max: 1.0 },
                { label: 'Darkpool', score: selectedSignal.dimension_scores.darkpool ?? 0, max: 1.5 },
              ].map((item) => {
                const pct = item.max > 0 ? (item.score / item.max) * 100 : 0
                return (
                  <div key={item.label} className="text-center">
                    <p className="text-[9px] text-[var(--text-secondary)] mb-1">{item.label}</p>
                    <div className="h-1.5 bg-[var(--bg-primary)] rounded-full overflow-hidden">
                      <div className="h-full bg-[var(--accent-blue)] rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                    <p className="text-[9px] text-[var(--text-primary)] mt-0.5">{item.score}/{item.max}</p>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
