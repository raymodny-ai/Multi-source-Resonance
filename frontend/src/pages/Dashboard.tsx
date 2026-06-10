import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDashboardScores, useRecentAlerts } from '../api/dashboard'
import { useTimezoneStore } from '../stores/timezoneStore'
import { useStalenessStore } from '../stores/stalenessStore'
import DimensionCard from '../components/DimensionCard'
import { formatCurrency, formatPercent, formatDecimal, formatOI, formatCompact } from '../utils/format'
import { formatTime, formatRelativeTime } from '../utils/time'
import { ALERT_LEVEL_COLORS, ALERT_LEVEL_LABELS } from '../types/common'
import type { AlertLevel } from '../types/common'
import type { DashboardScores } from '../types/api'

export default function Dashboard() {
  const navigate = useNavigate()
  const timezone = useTimezoneStore((s) => s.timezone)
  const updateSource = useStalenessStore((s) => s.updateSource)

  const { data, isLoading, isError } = useDashboardScores()
  const { data: recentAlerts } = useRecentAlerts(3)

  // Update staleness timestamps when data arrives
  useMemo(() => {
    if (data?.timestamp) {
      updateSource('dashboard', new Date(data.timestamp).getTime())
    }
  }, [data, updateSource])

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">实时仪表盘</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-40 rounded-xl skeleton" />
          ))}
        </div>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div>
        <h1 className="text-xl font-bold mb-4">实时仪表盘</h1>
        <div className="bg-[var(--bg-card)] border border-[var(--accent-red)]/30 rounded-xl p-6">
          <p className="text-[var(--accent-red)]">数据加载失败，请检查后端服务是否运行。</p>
        </div>
      </div>
    )
  }

  const { dimensions, resonance, hawkes } = data
  const { gex, vix, crypto, darkpool } = dimensions
  const now = Date.now()

  return (
    <div className="space-y-4 max-w-[1600px]">
      <h1 className="text-xl font-bold">实时仪表盘</h1>

      {/* Four dimension cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* GEX Card */}
        <DimensionCard
          title="GEX Gamma 敞口"
          score={gex.score}
          maxScore={1.5}
          state={gex.state}
          details={gex.details}
          lastUpdatedAt={now}
          onClick={() => navigate('/darkpool')}
        >
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between">
              <span>本地 GEX</span>
              <span className="text-[var(--text-primary)]">{formatCurrency(gex.gex_local)}</span>
            </div>
            <div className="flex justify-between">
              <span>校准 GEX</span>
              <span className="text-[var(--accent-green)]">{formatCurrency(gex.gex_calibrated)}</span>
            </div>
            <div className="flex justify-between">
              <span>Put Wall</span>
              <span className="text-[var(--text-primary)]">{gex.put_wall_level}</span>
            </div>
            <div className="flex justify-between">
              <span>Flip Zone</span>
              <span className="text-[var(--text-primary)]">{gex.flip_zone_lower}-{gex.flip_zone_upper}</span>
            </div>
          </div>
        </DimensionCard>

        {/* VIX Card */}
        <DimensionCard
          title="VIX 恐慌指数"
          score={vix.score}
          maxScore={1.0}
          state={vix.state}
          details={vix.details}
          lastUpdatedAt={now}
          onClick={() => navigate('/signals')}
        >
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between">
              <span>VIX Spot</span>
              <span className="text-[var(--text-primary)]">{formatDecimal(vix.vix_spot, 1)}</span>
            </div>
            <div className="flex justify-between">
              <span>VX1 / VX2</span>
              <span className="text-[var(--text-primary)]">{formatDecimal(vix.vx1, 1)}/{formatDecimal(vix.vx2, 1)}</span>
            </div>
            <div className="flex justify-between">
              <span>期限结构</span>
              <span
                className={vix.term_structure_ratio < 1 ? 'text-[var(--accent-red)]' : 'text-[var(--accent-green)]'}
              >
                {formatDecimal(vix.term_structure_ratio, 2)}
              </span>
            </div>
          </div>
        </DimensionCard>

        {/* Crypto Card */}
        <DimensionCard
          title="加密衍生品"
          score={crypto.score}
          maxScore={1.0}
          state={crypto.state}
          details={crypto.details}
          lastUpdatedAt={now}
        >
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between">
              <span>BTC 资金费率</span>
              <span
                className={crypto.btc_funding_rate > 0 ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}
              >
                {formatDecimal(crypto.btc_funding_rate, 4)}
              </span>
            </div>
            <div className="flex justify-between">
              <span>BTC OI</span>
              <span className="text-[var(--text-primary)]">{formatOI(crypto.btc_oi)}</span>
            </div>
            <div className="flex justify-between">
              <span>OI 1h 变化</span>
              <span
                className={crypto.oi_change_1h < 0 ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}
              >
                {formatPercent(crypto.oi_change_1h, 1)}
              </span>
            </div>
          </div>
        </DimensionCard>

        {/* Darkpool Card */}
        <DimensionCard
          title="暗盘三驾马车"
          score={darkpool.score}
          maxScore={1.5}
          state={darkpool.state}
          details={darkpool.details}
          lastUpdatedAt={now}
          onClick={() => navigate('/darkpool')}
        >
          <div className="space-y-0.5 text-[10px] text-[var(--text-secondary)]">
            <div className="flex justify-between">
              <span>DIX</span>
              <span className={darkpool.dix_signal ? 'text-[var(--accent-green)]' : 'text-[var(--text-secondary)]'}>
                {formatPercent(darkpool.dix_value)} {darkpool.dix_signal ? '✅' : ''}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Short Vol</span>
              <span className={darkpool.short_ratio_signal ? 'text-[var(--accent-green)]' : 'text-[var(--text-secondary)]'}>
                {formatPercent(darkpool.short_ratio)} {darkpool.short_ratio_signal ? '✅' : ''}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Stockgrid</span>
              <span className={darkpool.stockgrid_signal ? 'text-[var(--accent-green)]' : 'text-[var(--text-secondary)]'}>
                {darkpool.stockgrid_signal ? '✅' : '--'}
              </span>
            </div>
          </div>
        </DimensionCard>
      </div>

      {/* Resonance score bar */}
      <div
        className="rounded-xl p-4 border-2 transition-all"
        style={{
          borderColor: ALERT_LEVEL_COLORS[resonance.alert_level],
          backgroundColor: `${ALERT_LEVEL_COLORS[resonance.alert_level]}08`,
        }}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-semibold">共振得分</span>
          <span
            className="text-xs font-bold px-2 py-0.5 rounded"
            style={{
              backgroundColor: ALERT_LEVEL_COLORS[resonance.alert_level],
              color: '#fff',
            }}
          >
            {ALERT_LEVEL_LABELS[resonance.alert_level]}
          </span>
        </div>

        {/* Progress bar */}
        <div className="relative h-3 bg-[var(--bg-primary)] rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${resonance.resonance_pct}%`,
              backgroundColor: ALERT_LEVEL_COLORS[resonance.alert_level],
            }}
          />
        </div>

        <div className="flex items-center justify-between mt-2">
          <span className="text-2xl font-bold" style={{ color: ALERT_LEVEL_COLORS[resonance.alert_level] }}>
            {resonance.total_score.toFixed(1)}/{resonance.max_score.toFixed(1)}
          </span>
          <span className="text-xs text-[var(--text-secondary)]">
            {resonance.resonance_pct.toFixed(0)}%
          </span>
        </div>

        {/* Trigger conditions */}
        <div className="flex flex-wrap gap-2 mt-3">
          {[
            { label: 'GEX', active: gex.score > 0 },
            { label: 'VIX', active: vix.score > 0 },
            { label: 'Crypto', active: crypto.score > 0 },
            { label: 'Darkpool', active: darkpool.score > 0 },
            { label: 'Hawkes', active: hawkes.branching_ratio < 0.7 },
          ].map((cond) => (
            <span
              key={cond.label}
              className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded ${
                cond.active
                  ? 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]'
                  : 'bg-[var(--border)]/30 text-[var(--text-secondary)]'
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${cond.active ? 'bg-[var(--accent-green)]' : 'bg-[var(--text-secondary)]'}`} />
              {cond.label}
            </span>
          ))}
        </div>
      </div>

      {/* Recent alerts */}
      {recentAlerts && recentAlerts.length > 0 && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">最近告警</h3>
          <div className="flex flex-wrap gap-2">
            {recentAlerts.map((alert) => (
              <button
                key={alert.id}
                onClick={() => navigate('/alerts')}
                className="flex items-center gap-1.5 text-xs px-2 py-1 rounded border border-[var(--border)] hover:border-white/30 transition-colors"
              >
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: ALERT_LEVEL_COLORS[alert.alert_level as AlertLevel] }}
                />
                <span className="text-[var(--text-secondary)]">
                  {formatTime(alert.trigger_time, timezone)}
                </span>
                <span className="font-medium">
                  {ALERT_LEVEL_LABELS[alert.alert_level as AlertLevel]}
                </span>
                <span className="text-[var(--text-secondary)]">
                  {alert.total_score.toFixed(1)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Last updated timestamp */}
      <p className="text-[10px] text-[var(--text-secondary)] text-right">
        最后更新: {formatTime(data.timestamp, timezone, 'HH:mm:ss')}
        {' '}({formatRelativeTime(data.timestamp)})
      </p>
    </div>
  )
}
