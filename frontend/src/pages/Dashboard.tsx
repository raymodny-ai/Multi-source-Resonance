import { useMemo, useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDashboardScores, useRecentAlerts, useGEXCurve, useCrossAssetHeatmap, useResonanceHistory } from '../api/dashboard'
import { useStalenessStore } from '../stores/stalenessStore'
import { useAutoPollingStatus } from '../api/system'
import { formatCurrency, formatPercent, formatDecimal, formatOI } from '../utils/format'
import { formatTime, formatRelativeTime } from '../utils/time'
import { ALERT_LEVEL_COLORS, ALERT_LEVEL_LABELS, HAWKES_STATE_COLORS, HAWKES_STATE_LABELS } from '../types/common'
import type { AlertLevel } from '../types/common'
import type { DashboardScores } from '../types/api'
import { Pause, Play, RefreshCw, AlertTriangle } from 'lucide-react'
import ResonanceGauge from '../components/ResonanceGauge'
import GEXCurveChart from '../components/GEXCurveChart'
import CrossAssetHeatmap from '../components/CrossAssetHeatmap'
import HistoricalTrend from '../components/HistoricalTrend'

function HawkesProgressBar({ branchingRatio, state }: { branchingRatio: number; state: string }) {
  const pct = Math.min((branchingRatio / 1.0) * 100, 100)
  const color = HAWKES_STATE_COLORS[state] ?? '#64748b'
  const label = HAWKES_STATE_LABELS[state] ?? state
  const isCritical = state === 'CRITICAL' || state === 'SUPERCRITICAL'

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-[var(--text-primary)]">Hawkes 衰竭概率</h3>
        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: `${color}20`, color }}>
          {label}
        </span>
      </div>
      <div className="relative h-2 bg-[var(--bg-primary)] rounded-full overflow-hidden mb-1">
        <div
          className={`h-full rounded-full transition-all duration-700 ${isCritical ? 'animate-pulse' : ''}`}
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
        {/* Critical threshold line at 0.7 */}
        <div className="absolute top-0 bottom-0 w-px bg-[var(--accent-yellow)]" style={{ left: '70%' }} />
        <div className="absolute top-0 bottom-0 w-px bg-[var(--accent-red)]" style={{ left: '90%' }} />
      </div>
      <div className="flex justify-between text-[10px] text-[var(--text-secondary)]">
        <span>分支比: {branchingRatio.toFixed(2)}</span>
        <span>{pct.toFixed(0)}%</span>
      </div>
      <div className="flex justify-between text-[9px] text-[var(--text-secondary)] mt-0.5">
        <span style={{ color: 'var(--accent-green)' }}>0 安全区</span>
        <span style={{ color: 'var(--accent-yellow)' }}>0.7 警戒</span>
        <span style={{ color: 'var(--accent-red)' }}>0.9 临界</span>
        <span>1.0 自激</span>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const updateSource = useStalenessStore((s) => s.updateSource)
  const getLastUpdated = useStalenessStore((s) => s.getLastUpdated)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [manualTick, setManualTick] = useState(0)

  const { data, isLoading, isError, refetch } = useDashboardScores()
  const { data: recentAlerts } = useRecentAlerts(5)
  const { data: pollingStatus } = useAutoPollingStatus()
  const { data: gexCurveData, isLoading: gexCurveLoading } = useGEXCurve(30)
  const { data: heatmapData, isLoading: heatmapLoading } = useCrossAssetHeatmap()
  const { data: resonanceTrend, isLoading: trendLoading } = useResonanceHistory(30)

  // Track when auto-polling was last disabled
  const autoPollingOffSince = useRef<number | null>(null)
  useEffect(() => {
    if (pollingStatus && !pollingStatus.enabled) {
      if (autoPollingOffSince.current === null) {
        autoPollingOffSince.current = Date.now()
      }
    } else {
      autoPollingOffSince.current = null
    }
  }, [pollingStatus])

  // Auto-polling stale: disabled > 30 minutes
  const autoPollingStale =
    pollingStatus &&
    !pollingStatus.enabled &&
    autoPollingOffSince.current !== null &&
    (Date.now() - autoPollingOffSince.current) > 30 * 60 * 1000

  // Track staleness
  useEffect(() => {
    if (data?.timestamp) {
      updateSource('dashboard', new Date(data.timestamp).getTime())
    }
  }, [data, updateSource])

  // Manual refresh toggle - force refetch interval to 30s or Infinity
  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => refetch(), 30_000)
    return () => clearInterval(timer)
  }, [autoRefresh, refetch])

  const lastUpdated = getLastUpdated('dashboard')
  const staleSeconds = lastUpdated ? Math.floor((Date.now() - lastUpdated) / 1000) : 0
  const isStale = staleSeconds > 60

  const handleRefresh = useCallback(() => {
    refetch()
    setManualTick((t) => t + 1)
  }, [refetch])

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold text-[var(--text-primary)]">实时仪表盘</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-44 rounded-xl skeleton" />
          ))}
        </div>
        <div className="h-20 rounded-xl skeleton" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold text-[var(--text-primary)]">实时仪表盘</h1>
        <div className="bg-[var(--bg-card)] border border-[var(--accent-red)]/30 rounded-xl p-8 text-center">
          <p className="text-[var(--accent-red)] text-sm">⚠️ 数据加载失败</p>
          <p className="text-xs text-[var(--text-secondary)] mt-1">请确认后端服务是否运行在 localhost:8000</p>
          <button
            onClick={handleRefresh}
            className="mt-4 px-4 py-2 rounded-lg bg-[var(--accent-blue)] text-white text-xs hover:opacity-90"
          >
            重试
          </button>
        </div>
      </div>
    )
  }

  const { dimensions, resonance, hawkes } = data
  const { gex, vix, crypto, darkpool, cross_asset } = dimensions
  const isLevel3 = resonance.alert_level === 'LEVEL_3'

  return (
    <div className="space-y-4 max-w-[1600px]">
      {/* Header with controls */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-[var(--text-primary)]">实时仪表盘</h1>
        <div className="flex items-center gap-2">
          {autoPollingStale && (
            <span className="text-[var(--accent-yellow)]" title="自动轮询已关闭超过30分钟，数据严重过时">
              <AlertTriangle size={14} />
            </span>
          )}
          <span className={`text-[10px] flex items-center gap-1 ${isStale ? 'text-[var(--accent-yellow)]' : 'text-[var(--accent-green)]'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${isStale ? 'bg-[var(--accent-yellow)] animate-pulse' : 'bg-[var(--accent-green)]'}`} />
            {isStale ? `延迟 ${staleSeconds}s` : 'LIVE'}
          </span>
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className="p-1.5 rounded-md text-[var(--text-secondary)] hover:text-white hover:bg-white/5 transition-colors"
            title={autoRefresh ? '暂停自动刷新' : '恢复自动刷新'}
          >
            {autoRefresh ? <Pause size={14} /> : <Play size={14} />}
          </button>
          <button
            onClick={handleRefresh}
            className="p-1.5 rounded-md text-[var(--text-secondary)] hover:text-white hover:bg-white/5 transition-colors"
            title="立即刷新"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Five dimension cards - responsive grid */}
      <div className={`grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4 ${isStale ? 'opacity-60' : ''}`}>
        {/* GEX Card */}
        <div
          className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:border-white/20 transition-all group"
          onClick={() => navigate('/darkpool')}
        >
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">GEX Gamma 敞口</h3>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: `${gex.state === 'FLIP_ON' ? '#22c55e' : gex.state === 'NEGATIVE' ? '#ef4444' : '#64748b'}20`,
                color: gex.state === 'FLIP_ON' ? '#22c55e' : gex.state === 'NEGATIVE' ? '#ef4444' : '#94a3b8',
              }}
            >
              {gex.state === 'FLIP_ON' ? 'FLIP ON' : gex.state}
            </span>
          </div>
          <div className="text-2xl font-bold mb-1" style={{ color: gex.state === 'FLIP_ON' ? '#22c55e' : gex.state === 'NEGATIVE' ? '#ef4444' : '#f1f5f9' }}>
            {formatCurrency(gex.gex_calibrated)}
          </div>
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between"><span>本地 GEX</span><span className="text-[var(--text-primary)]">{formatCurrency(gex.gex_local)}</span></div>
            <div className="flex justify-between"><span>Put Wall</span><span className="text-[var(--text-primary)]">{gex.put_wall_level}</span></div>
            <div className="flex justify-between"><span>Flip Zone</span><span className="text-[var(--text-primary)]">{gex.flip_zone_lower} - {gex.flip_zone_upper}</span></div>
          </div>
          <div className="mt-2 flex items-center gap-1">
            <div className="flex-1 h-1 bg-[var(--bg-primary)] rounded-full overflow-hidden">
              <div className="h-full bg-[#22c55e] rounded-full transition-all duration-700" style={{ width: `${(gex.score / 1.5) * 100}%` }} />
            </div>
            <span className="text-[10px] text-[var(--text-secondary)]">{gex.score.toFixed(1)}/1.5</span>
          </div>
        </div>

        {/* VIX Card */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:border-white/20 transition-all" onClick={() => navigate('/signals')}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">VIX 期限结构</h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: `${vix.state === 'CONTANGO' ? '#22c55e' : vix.state === 'BACKWARDATION' ? '#ef4444' : '#64748b'}20`,
                color: vix.state === 'CONTANGO' ? '#22c55e' : vix.state === 'BACKWARDATION' ? '#ef4444' : '#94a3b8',
              }}>
              {vix.state}
            </span>
          </div>
          <div className="text-2xl font-bold mb-1 text-[var(--text-primary)]">{formatDecimal(vix.vix_spot, 1)}</div>
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between"><span>VX1 / VX2</span><span className="text-[var(--text-primary)]">{formatDecimal(vix.vx1, 1)}/{formatDecimal(vix.vx2, 1)}</span></div>
            <div className="flex justify-between"><span>期限结构比</span>
              <span className={vix.term_structure_ratio < 1 ? 'text-[var(--accent-red)]' : 'text-[var(--accent-green)]'}>{formatDecimal(vix.term_structure_ratio, 2)}</span>
            </div>
            <div className="flex justify-between"><span>恐慌溢价</span><span className="text-[var(--text-primary)]">{formatDecimal(vix.panic_premium, 2)}</span></div>
          </div>
          <div className="mt-2 flex items-center gap-1">
            <div className="flex-1 h-1 bg-[var(--bg-primary)] rounded-full overflow-hidden">
              <div className="h-full bg-[#22c55e] rounded-full transition-all duration-700" style={{ width: `${(vix.score / 1.0) * 100}%` }} />
            </div>
            <span className="text-[10px] text-[var(--text-secondary)]">{vix.score.toFixed(1)}/1.0</span>
          </div>
        </div>

        {/* Crypto Card */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:border-white/20 transition-all">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Crypto 去杠杆</h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: `${crypto.state === 'CLEANUP_COMPLETE' ? '#22c55e' : crypto.state === 'LEVERAGE_BUILDUP' ? '#ef4444' : '#64748b'}20`,
                color: crypto.state === 'CLEANUP_COMPLETE' ? '#22c55e' : crypto.state === 'LEVERAGE_BUILDUP' ? '#ef4444' : '#94a3b8',
              }}>
              {crypto.state === 'CLEANUP_COMPLETE' ? 'CLEANUP COMPLETE' : crypto.state}
            </span>
          </div>
          <div className="text-2xl font-bold mb-1 text-[var(--text-primary)]">{formatOI(crypto.btc_oi)}</div>
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between"><span>BTC 资金费率</span>
              <span className={crypto.btc_funding_rate > 0 ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}>{formatDecimal(crypto.btc_funding_rate, 4)}</span>
            </div>
            <div className="flex justify-between"><span>OI 1h 变化</span>
              <span className={crypto.oi_change_1h < 0 ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}>{formatPercent(crypto.oi_change_1h, 1)}</span>
            </div>
            <div className="flex justify-between"><span>杠杆清洗</span>
              <span className={crypto.leverage_cleanup_confirmed ? 'text-[var(--accent-green)]' : 'text-[var(--text-secondary)]'}>
                {crypto.leverage_cleanup_confirmed ? '✅ 已完成' : '⏳ 进行中'}
              </span>
            </div>
          </div>
          <div className="mt-2 flex items-center gap-1">
            <div className="flex-1 h-1 bg-[var(--bg-primary)] rounded-full overflow-hidden">
              <div className="h-full bg-[#22c55e] rounded-full transition-all duration-700" style={{ width: `${(crypto.score / 1.0) * 100}%` }} />
            </div>
            <span className="text-[10px] text-[var(--text-secondary)]">{crypto.score.toFixed(1)}/1.0</span>
          </div>
        </div>

        {/* Darkpool Card */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:border-white/20 transition-all" onClick={() => navigate('/darkpool')}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">暗盘综合</h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: `${darkpool.state === 'TRIGGERED_3OF3' || darkpool.state === 'STRONG_ACCUMULATION' ? '#22c55e' : '#64748b'}20`,
                color: darkpool.state === 'TRIGGERED_3OF3' || darkpool.state === 'STRONG_ACCUMULATION' ? '#22c55e' : '#94a3b8',
              }}>
              {darkpool.state === 'TRIGGERED_3OF3' ? '3/3 SIGNALS' : darkpool.state}
            </span>
          </div>
          <div className="text-2xl font-bold mb-1 text-[var(--text-primary)]">{formatPercent(darkpool.dix_value, 1)}</div>
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between"><span>DIX</span>
              <span className={darkpool.dix_signal ? 'text-[var(--accent-green)]' : ''}>{formatPercent(darkpool.dix_value, 1)} {darkpool.dix_signal ? '✅' : ''}</span>
            </div>
            <div className="flex justify-between"><span>Short Vol</span>
              <span className={darkpool.short_ratio_signal ? 'text-[var(--accent-green)]' : ''}>{formatPercent(darkpool.short_ratio, 1)} {darkpool.short_ratio_signal ? '✅' : ''}</span>
            </div>
            <div className="flex justify-between"><span>Stockgrid</span>
              <span className={darkpool.stockgrid_signal ? 'text-[var(--accent-green)]' : ''}>{darkpool.stockgrid_signal ? '✅ 触发' : '--'}</span>
            </div>
          </div>
          <div className="mt-2 flex items-center gap-1">
            <div className="flex-1 h-1 bg-[var(--bg-primary)] rounded-full overflow-hidden">
              <div className="h-full bg-[#22c55e] rounded-full transition-all duration-700" style={{ width: `${(darkpool.score / 1.5) * 100}%` }} />
            </div>
            <span className="text-[10px] text-[var(--text-secondary)]">{darkpool.score.toFixed(1)}/1.5</span>
          </div>
        </div>

        {/* Cross-Asset Card */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:border-white/20 transition-all">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">跨资产共振</h3>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: `${cross_asset.resonance_strength === 'Strong' ? '#22c55e' : cross_asset.resonance_strength === 'Moderate' ? '#eab308' : '#64748b'}20`,
                color: cross_asset.resonance_strength === 'Strong' ? '#22c55e' : cross_asset.resonance_strength === 'Moderate' ? '#eab308' : '#94a3b8',
              }}
            >
              {cross_asset.resonance_strength === 'None' ? 'NONE' : cross_asset.resonance_strength.toUpperCase()}
            </span>
          </div>
          <div className="text-2xl font-bold mb-1 text-[var(--text-primary)]">{cross_asset.coherence_score.toFixed(0)}</div>
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between"><span>一致性得分</span>
              <span className={cross_asset.coherence_score > 60 ? 'text-[var(--accent-green)]' : cross_asset.coherence_score > 40 ? 'text-[var(--accent-yellow)]' : 'text-[var(--text-secondary)]'}>
                {cross_asset.coherence_score.toFixed(1)}/100
              </span>
            </div>
            <div className="flex justify-between"><span>方向</span>
              <span className={cross_asset.alignment_direction === 'BULLISH' ? 'text-[var(--accent-green)]' : cross_asset.alignment_direction === 'BEARISH' ? 'text-[var(--accent-red)]' : 'text-[var(--text-secondary)]'}>
                {cross_asset.alignment_direction}
              </span>
            </div>
            <div className="flex justify-between"><span>对齐资产数</span>
              <span className="text-[var(--text-primary)]">{cross_asset.alignment_count}/4</span>
            </div>
          </div>
          <div className="mt-2 flex items-center gap-1">
            <div className="flex-1 h-1 bg-[var(--bg-primary)] rounded-full overflow-hidden">
              <div className="h-full bg-[#8b5cf6] rounded-full transition-all duration-700" style={{ width: `${cross_asset.coherence_score}%` }} />
            </div>
            <span className="text-[10px] text-[var(--text-secondary)]">{cross_asset.score.toFixed(1)}/0.15</span>
          </div>
        </div>
      </div>

      {/* Resonance Banner */}
      <div
        className={`rounded-xl p-4 border-2 transition-all ${isLevel3 ? 'pulse-alert' : ''}`}
        style={{
          borderColor: ALERT_LEVEL_COLORS[resonance.alert_level],
          backgroundColor: `${ALERT_LEVEL_COLORS[resonance.alert_level]}08`,
        }}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-semibold">共振得分</span>
          <span className="text-xs font-bold px-2 py-0.5 rounded text-white"
            style={{ backgroundColor: ALERT_LEVEL_COLORS[resonance.alert_level] }}>
            {ALERT_LEVEL_LABELS[resonance.alert_level]}
          </span>
        </div>

        {/* Main progress bar */}
        <div className="relative h-4 bg-[var(--bg-primary)] rounded-full overflow-hidden mb-2">
          {/* Section dividers for each dimension's max contribution */}
          {[
            { pct: 30, color: '#22c55e30' },    // GEX 1.5/5.0
            { pct: 50, color: '#3b82f630' },     // VIX 1.0/5.0
            { pct: 70, color: '#eab30830' },      // Crypto 1.0/5.0
            { pct: 85, color: '#a855f730' },      // Darkpool 0.75/5.0
            { pct: 100, color: '#8b5cf630' },     // Cross-Asset 0.75/5.0
          ].map((div) => (
            <div key={div.pct} className="absolute top-0 bottom-0 w-px bg-white/20" style={{ left: `${div.pct}%` }} />
          ))}
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${resonance.resonance_pct}%`,
              backgroundColor: ALERT_LEVEL_COLORS[resonance.alert_level],
            }}
          />
        </div>

        <div className="flex items-center justify-between">
          <span className="text-2xl font-bold" style={{ color: ALERT_LEVEL_COLORS[resonance.alert_level] }}>
            {resonance.total_score.toFixed(1)}<span className="text-sm text-[var(--text-secondary)]">/{resonance.max_score.toFixed(1)}</span>
          </span>
          <span className="text-xs text-[var(--text-secondary)]">{resonance.resonance_pct.toFixed(0)}%</span>
        </div>

        {/* Trigger conditions chips */}
        <div className="flex flex-wrap gap-2 mt-3">
          {[
            { label: 'GEX', active: gex.score > 0, score: gex.score, max: 1.5 },
            { label: 'VIX', active: vix.score > 0, score: vix.score, max: 1.0 },
            { label: 'Crypto', active: crypto.score > 0, score: crypto.score, max: 1.0 },
            { label: 'Darkpool', active: darkpool.score > 0, score: darkpool.score, max: 0.75 },
            { label: 'Cross-Asset', active: cross_asset.coherence_score > 50, score: cross_asset.coherence_score, max: 100 },
            { label: 'Hawkes', active: hawkes.branching_ratio < 0.7, score: hawkes.branching_ratio, max: 0 },
          ].map((cond) => (
            <span
              key={cond.label}
              className={`inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full border transition-all ${
                cond.active
                  ? 'border-[var(--accent-green)]/30 bg-[var(--accent-green)]/10 text-[var(--accent-green)]'
                  : 'border-[var(--border)] text-[var(--text-secondary)]'
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${cond.active ? 'bg-[var(--accent-green)]' : 'bg-[var(--text-secondary)]'}`} />
              {cond.label}
              {cond.max > 0 && <span className="opacity-60">({cond.score}/{cond.max})</span>}
            </span>
          ))}
        </div>
      </div>

      {/* Hawkes Progress Bar */}
      <HawkesProgressBar branchingRatio={hawkes.branching_ratio} state={hawkes.state} />

      {/* Resonance Gauge + Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ResonanceGauge resonance={resonance} />
        <GEXCurveChart data={gexCurveData} isLoading={gexCurveLoading} />
        <HistoricalTrend data={resonanceTrend} isLoading={trendLoading} />
      </div>

      {/* Cross-Asset Heatmap */}
      <CrossAssetHeatmap data={heatmapData} isLoading={heatmapLoading} />

      {/* Recent alerts */}
      {recentAlerts && recentAlerts.length > 0 && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">最近告警</h3>
            <button
              onClick={() => navigate('/alerts')}
              className="text-[10px] text-[var(--accent-blue)] hover:underline"
            >
              查看全部 →
            </button>
          </div>
          <div className="space-y-1">
            {recentAlerts.map((alert) => (
              <button
                key={alert.id}
                onClick={() => navigate('/alerts')}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left hover:bg-white/5 transition-colors group"
              >
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: ALERT_LEVEL_COLORS[alert.alert_level as AlertLevel] }} />
                <span className="text-[10px] text-[var(--text-secondary)] w-12 shrink-0">
                  {formatTime(alert.trigger_time, 'America/New_York', 'HH:mm')}
                </span>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded text-white"
                  style={{ backgroundColor: ALERT_LEVEL_COLORS[alert.alert_level as AlertLevel] }}>
                  {ALERT_LEVEL_LABELS[alert.alert_level as AlertLevel]}
                </span>
                <span className="text-[10px] text-[var(--text-primary)]">{alert.total_score.toFixed(1)}</span>
                <span className="text-[10px] text-[var(--text-secondary)] ml-auto">
                  {alert.acknowledged ? '✅ 已确认' : '⬜ 未确认'}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Footer - last update timestamp */}
      <p className="text-[10px] text-[var(--text-secondary)] text-right">
        最后更新: {formatTime(data.timestamp, 'America/New_York', 'HH:mm:ss')} EST
        {' · '}{formatRelativeTime(data.timestamp)}
      </p>
    </div>
  )
}
