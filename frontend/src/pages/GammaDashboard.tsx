import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { useGEXSymbols, useGEXLatest, useGEXHistory, useGEXLevels, useGEXSummary, useGEXStrikes, useGEXDashboardView } from '../api/gexmetrix'

// C: BFF 模式开关 - true=用聚合接口, false=6 个独立 hook
const USE_BFF_DASHBOARD = true
import { useStalenessStore } from '../stores/stalenessStore'
import { useTimezoneStore } from '../stores/timezoneStore'
import { formatCurrency, formatCompact } from '../utils/format'
import { formatTime } from '../utils/time'
import type { GEXSymbolStatus } from '../types/api'
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  ArrowUp,
  ArrowDown,
  BarChart3,
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  LineChart,
  Line,
  ComposedChart,
  Legend,
  Cell,
} from 'recharts'

// ── 颜色常量 ──
const POS_GAMMA = '#00D4AA'
const NEG_GAMMA = '#FF4D6D'
const ZERO_GAMMA = '#FFD700'
const FRESH_COLOR = '#22c55e'
const STALE_WARN_COLOR = '#eab308'
const STALE_COLOR = '#ef4444'

// ── 标的类别分组 ──
const SYMBOL_GROUPS: { label: string; symbols: string[] }[] = [
  { label: '核心标的', symbols: ['SPX', 'SPY', 'QQQ', 'VIX', 'IWM', 'NDX'] },
  { label: '指数', symbols: ['SPX', 'NDX', 'DJX', 'RUT'] },
]

function getFreshnessColor(ageMinutes: number | null): string {
  if (ageMinutes == null) return STALE_COLOR
  if (ageMinutes < 5) return FRESH_COLOR
  if (ageMinutes < 15) return STALE_WARN_COLOR
  return STALE_COLOR
}

function formatAge(ageMinutes: number | null): string {
  if (ageMinutes == null) return '--'
  if (ageMinutes < 1) return '<1m'
  if (ageMinutes < 60) return `${Math.round(ageMinutes)}m`
  const h = Math.floor(ageMinutes / 60)
  const m = Math.round(ageMinutes % 60)
  return `${h}h${m > 0 ? m + 'm' : ''}`
}

function formatGEX(value: number | null): string {
  if (value == null) return '--'
  const abs = Math.abs(value)
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000) return `${(value / 1_000).toFixed(2)}K`
  // 小于 1k 的值限制为 2 位小数，防止超高精度数字撑破 Tooltip
  return value.toFixed(2)
}

// ═══════════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════════
export default function GammaDashboard() {
  const updateSource = useStalenessStore((s) => s.updateSource)
  const getLastUpdated = useStalenessStore((s) => s.getLastUpdated)
  const timezone = useTimezoneStore((s) => s.timezone)

  const [selectedSymbol, setSelectedSymbol] = useState<string>('SPX')
  const [historyDays, setHistoryDays] = useState(7)
  const [sortKey, setSortKey] = useState<'symbol' | 'net_gex' | 'age'>('symbol')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [autoRefresh, setAutoRefresh] = useState(true)
  // 一.1: 仅 SPX 支持 90 天 SqueezeMetrics 历史, 非 SPX 强制上限 3 天 (GEXMetrix 边界)
  const HISTORY_LONG_THRESHOLD = 3
  const isLongHistory = historyDays > HISTORY_LONG_THRESHOLD
  const longHistoryRequiresSPX = selectedSymbol !== 'SPX' && isLongHistory
  const [longHistoryNotice, setLongHistoryNotice] = useState<string | null>(null)
  const lastRefreshRef = useRef<number>(Date.now())

  useEffect(() => {
    if (longHistoryRequiresSPX) {
      setHistoryDays(HISTORY_LONG_THRESHOLD)
      setLongHistoryNotice(
        `${selectedSymbol} 仅支持 ${HISTORY_LONG_THRESHOLD} 天历史 (GEXMetrix 数据边界)。仅 SPX 支持 90 天 (SqueezeMetrics)。`,
      )
      const t = setTimeout(() => setLongHistoryNotice(null), 5000)
      return () => clearTimeout(t)
    }
  }, [longHistoryRequiresSPX, selectedSymbol])

  // ── 数据查询 ──
  const { data: symbols, isLoading: symLoading } = useGEXSymbols()
  const { data: summary } = useGEXSummary()
  const { data: latest, isLoading: latestLoading, isError: latestError, error: latestErrorObj } = useGEXLatest(selectedSymbol)
  const { data: history, isLoading: histLoading } = useGEXHistory(selectedSymbol, historyDays)
  const { data: levels, isLoading: lvlsLoading } = useGEXLevels(selectedSymbol)
  // B: 真实逐 strike 数据
  const { data: strikesResp, isLoading: strikesLoading } = useGEXStrikes(selectedSymbol, 200)

  // C: BFF 聚合接口 (单次调用拿到全部数据)
  const bffResp = useGEXDashboardView(
    selectedSymbol,
    { history_days: 3, long_days: 90, strikes_limit: 200 }
  )
  const bffView = bffResp.data
  const bffLoading = bffResp.isLoading

  // ── 跟踪新鲜度 (三.2: 失败时也要同步 lastRefreshRef 并降级 UI) ──
  useEffect(() => {
    if (latest?.timestamp) {
      updateSource('gexmetrix', new Date(latest.timestamp).getTime())
      lastRefreshRef.current = Date.now()
    }
  }, [latest, updateSource])

  // ── 自动刷新 (盘中每5分钟) ──
  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => {
      // React Query 会自动 refetch
    }, 5 * 60 * 1000)
    return () => clearInterval(timer)
  }, [autoRefresh])

  // ── 排序后的标的列表 ──
  // 三.3: 移除 net_gex dead branch (UI 不暴露该选项, 留着是 dead code)
  const sortedSymbols = useMemo(() => {
    if (!symbols) return []
    const list = [...symbols]
    list.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'symbol') {
        cmp = (a.symbol || '').localeCompare(b.symbol || '')
      } else if (sortKey === 'age') {
        cmp = (a.age_minutes ?? 999) - (b.age_minutes ?? 999)
      }
      return sortDir === 'desc' ? -cmp : cmp
    })
    return list
  }, [symbols, sortKey, sortDir])

  // ── 历史图表数据 ──
  const historyData = useMemo(() => {
    if (!history) return []
    return history.map((pt) => ({
      timestamp: pt.timestamp,
      time: pt.timestamp ? pt.timestamp.slice(11, 16) : '',
      net_gex: pt.net_gex ?? 0,
      spot_price: pt.spot_price ?? 0,
    }))
  }, [history])

  // ── 行权价分布数据 (C: 优先 BFF, B: 真实 strikes, fallback 到 levels 派生) ──
  const strikesData = useMemo(() => {
    const levels_data = bffView?.levels ?? levels
    const spot = levels_data?.spot_price ?? 5000
    const callWall = levels_data?.call_wall ?? spot * 1.05
    const putWall = levels_data?.put_wall ?? spot * 0.95
    const zeroGamma = levels_data?.zero_gamma_level ?? spot

    // C: 优先用 BFF 真实 strikes; B: 回退到 useGEXStrikes hook
    const bffStrikes = bffView?.strikes?.strikes
    const hookStrikes = strikesResp?.strikes
    const realStrikes =
      bffStrikes && bffStrikes.length > 0
        ? bffStrikes
        : hookStrikes && hookStrikes.length > 0
        ? hookStrikes
        : null
    const realSpot = bffView?.strikes?.spot_price ?? spot

    if (realStrikes) {
      return {
        strikes: realStrikes,
        zeroGamma,
        callWall,
        putWall,
        spot: realSpot,
        isReal: true,
        source: bffStrikes ? 'bff' : 'hook',
      }
    }

    // fallback: 从 levels 派生 (向后兼容)
    const strikes: { strike: number; call_gex: number; put_gex: number }[] = []
    const step = spot * 0.005
    for (let s = spot * 0.85; s <= spot * 1.15; s += step) {
      const distCall = s - callWall
      const distPut = putWall - s
      const callVal = Math.max(0, Math.exp(-distCall * distCall / (2 * (spot * 0.03) ** 2)) * 5e7)
      const putVal = Math.max(0, Math.exp(-distPut * distPut / (2 * (spot * 0.03) ** 2)) * 5e7)
      strikes.push({
        strike: Math.round(s),
        call_gex: Math.round(callVal),
        put_gex: -Math.round(putVal),
      })
    }
    return { strikes, zeroGamma, callWall, putWall, spot, isReal: false, source: 'simulated' }
  }, [levels, strikesResp, bffView])

  const spotPrice = levels?.spot_price
  const spotPriceDeviation =
    spotPrice && levels?.zero_gamma_level
      ? ((spotPrice - levels.zero_gamma_level) / levels.zero_gamma_level) * 100
      : null

  // ── 最后一次刷新时间 ──
  const lastUpdatedStaleness = getLastUpdated('gexmetrix')

  return (
    <div className="flex flex-col h-full gap-4">
      {/* ═══ 顶部控制栏 ═══ */}
      <div className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-3 shrink-0">
        <BarChart3 size={20} className="text-[var(--accent-blue)]" />
        <h2 className="text-sm font-bold text-[var(--text-primary)]">Gamma 仪表盘</h2>

        {/* 标的选择器 */}
        <div className="flex items-center gap-2 ml-4">
          <label className="text-xs text-[var(--text-secondary)]">标的:</label>
          <select
            value={selectedSymbol}
            onChange={(e) => setSelectedSymbol(e.target.value)}
            className="bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg px-3 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-blue)]"
          >
            {SYMBOL_GROUPS.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.symbols.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        {/* 数据时间戳 */}
        <span className="text-xs text-[var(--text-secondary)] ml-auto">
          数据时间: {latest?.timestamp ? formatTime(latest.timestamp, timezone) : '--'}
        </span>

        {/* 新鲜度 */}
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{
            backgroundColor: symbols
              ? getFreshnessColor(
                  symbols.find((s) => s.symbol === selectedSymbol)?.age_minutes ?? null
                )
              : 'var(--text-secondary)',
          }}
          title={`数据年龄: ${formatAge(
            symbols?.find((s) => s.symbol === selectedSymbol)?.age_minutes ?? null
          )}`}
        />

        {/* 最后刷新 (三.2: 失败时显示错误态) */}
        <span
          className="text-xs"
          style={{
            color: latestError
              ? 'var(--accent-red, #ef4444)'
              : 'var(--text-secondary)',
          }}
          title={latestError ? `API 错误: ${latestErrorObj?.message ?? '未知'}` : undefined}
        >
          {latestError
            ? '⚠ 请求失败'
            : `刷新于 ${formatTime(new Date(lastRefreshRef.current).toISOString(), timezone)}`}
        </span>

        {/* 刷新按钮 */}
        <button
          onClick={() => setAutoRefresh(!autoRefresh)}
          className={`p-1.5 rounded-lg transition-colors ${
            autoRefresh ? 'text-[var(--accent-green)] bg-[var(--accent-green)]/10' : 'text-[var(--text-secondary)] hover:text-white'
          }`}
          title={autoRefresh ? '自动刷新中 (5分钟)' : '自动刷新已暂停'}
        >
          <RefreshCw size={16} className={autoRefresh ? 'animate-spin-slow' : ''} />
        </button>
      </div>

      {/* ═══ 主体: 左面板 + 主图区 ═══ */}
      <div className="flex gap-4 flex-1 min-h-0">
        {/* ── 左侧面板 (35%) ── */}
        <div className="w-[35%] min-w-[260px] bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between mb-3 shrink-0">
            <h3 className="text-xs font-semibold text-[var(--text-primary)]">
              标的清单 ({symbols?.length ?? 0})
            </h3>
            <div className="flex gap-1">
              <button
                onClick={() => { setSortKey('symbol'); setSortDir(sortDir === 'asc' ? 'desc' : 'asc') }}
                className={`text-[9px] px-1.5 py-0.5 rounded ${sortKey === 'symbol' ? 'bg-[var(--accent-blue)]/15 text-[var(--accent-blue)]' : 'text-[var(--text-secondary)]'}`}
              >
                名称
              </button>
              <button
                onClick={() => { setSortKey('age'); setSortDir(sortDir === 'asc' ? 'desc' : 'asc') }}
                className={`text-[9px] px-1.5 py-0.5 rounded ${sortKey === 'age' ? 'bg-[var(--accent-blue)]/15 text-[var(--accent-blue)]' : 'text-[var(--text-secondary)]'}`}
              >
                新鲜度
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1">
            {symLoading ? (
              <div className="text-xs text-[var(--text-secondary)] p-4 text-center">加载中...</div>
            ) : sortedSymbols.length === 0 ? (
              <div className="text-xs text-[var(--text-secondary)] p-4 text-center">
                暂无数据。请先执行手动采集。
              </div>
            ) : (
              sortedSymbols.map((item) => (
                <button
                  key={item.symbol}
                  onClick={() => setSelectedSymbol(item.symbol)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors ${
                    selectedSymbol === item.symbol
                      ? 'bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/30'
                      : 'hover:bg-white/5 border border-transparent'
                  }`}
                >
                  {/* 新鲜度指示 */}
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: getFreshnessColor(item.age_minutes) }}
                  />

                  {/* 标的名称 */}
                  <span className="text-xs font-medium text-[var(--text-primary)] w-12 shrink-0">
                    {item.symbol}
                  </span>

                  {/* Net GEX 方向指示 */}
                  <span className="text-[11px] text-[var(--text-secondary)]">
                    {formatAge(item.age_minutes)}
                  </span>

                  {/* 快照数量 */}
                  <span className="text-[10px] text-[var(--text-secondary)] ml-auto">
                    {item.snapshot_count} snap
                  </span>
                </button>
              ))
            )}
          </div>
        </div>

        {/* ── 主图区 (65%) ── */}
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          {/* 上部: GEX 行权价分布柱状图 */}
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex-1 min-h-[240px]">
            <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-3">
              GEX 行权价分布 — {selectedSymbol}
              {spotPrice && <span className="ml-2 text-[var(--text-secondary)]">现货 @ {spotPrice.toFixed(0)}</span>}
              {/* B: 真实数据时绿色 ✓ 徽章, fallback 到模拟时黄色 ⚠ 徽章 */}
              {strikesData.isReal ? (
                <span
                  className="ml-2 px-1.5 py-0.5 rounded text-[9px] font-bold"
                  style={{
                    backgroundColor: 'rgba(34, 197, 94, 0.15)',
                    color: '#22c55e',
                    border: '1px solid rgba(34, 197, 94, 0.4)',
                  }}
                  title={`真实 OI × Gamma 数据, ${strikesData.strikes.length} 个 strike`}
                >
                  ✓ 真实数据
                </span>
              ) : (
                <span
                  className="ml-2 px-1.5 py-0.5 rounded text-[9px] font-bold"
                  style={{
                    backgroundColor: 'rgba(234, 179, 8, 0.15)',
                    color: '#eab308',
                    border: '1px solid rgba(234, 179, 8, 0.4)',
                  }}
                  title="GEXMetrix 无逐 strike 数据, 此柱状图为高斯模拟, 非真实 OI 分布"
                >
                  ⚠ 模拟数据
                </span>
              )}
            </h3>
            <ResponsiveContainer width="100%" height="90%">
              <BarChart
                data={strikesData.strikes}
                margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                barCategoryGap="5%"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.5} />
                <XAxis
                  dataKey="strike"
                  tick={{ fontSize: 10, fill: 'var(--text-secondary)' }}
                  tickFormatter={(v: number) => v.toFixed(0)}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: 'var(--text-secondary)' }}
                  tickFormatter={(v: number) => (Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : String(v))}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: '8px',
                    fontSize: '12px',
                    color: 'var(--text-primary)',
                  }}
                  formatter={((value: unknown, name: unknown) => [
                    formatCurrency(Math.abs(Number(value))),
                    name === 'call_gex' ? 'Call GEX' : 'Put GEX',
                  ]) as never}
                  labelFormatter={((label: unknown) => `行权价: ${label}`) as never}
                />
                <Bar dataKey="call_gex" fill={POS_GAMMA} name="call_gex" radius={[1, 1, 0, 0]} />
                <Bar dataKey="put_gex" fill={NEG_GAMMA} name="put_gex" radius={[1, 1, 0, 0]} />
                {/* Zero Gamma 虚线 */}
                <ReferenceLine
                  x={Math.round(strikesData.zeroGamma)}
                  stroke={ZERO_GAMMA}
                  strokeDasharray="6 4"
                  strokeWidth={1.5}
                  label={{
                    value: `Zero Γ ${strikesData.zeroGamma?.toFixed(0)}`,
                    fontSize: 10,
                    fill: ZERO_GAMMA,
                    position: 'top',
                  }}
                />
                {/* Call Wall 虚线 */}
                {strikesData.callWall && (
                  <ReferenceLine
                    x={Math.round(strikesData.callWall)}
                    stroke={POS_GAMMA}
                    strokeDasharray="3 3"
                    strokeWidth={1}
                    opacity={0.7}
                  />
                )}
                {/* Put Wall 虚线 */}
                {strikesData.putWall && (
                  <ReferenceLine
                    x={Math.round(strikesData.putWall)}
                    stroke={NEG_GAMMA}
                    strokeDasharray="3 3"
                    strokeWidth={1}
                    opacity={0.7}
                  />
                )}
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* 下部: 历史 Net GEX 走势图 (双轴) */}
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex-1 min-h-[200px]">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-[var(--text-primary)]">
                Net GEX 历史走势 — {selectedSymbol}
                {longHistoryNotice && (
                  <span
                    className="ml-2 px-1.5 py-0.5 rounded text-[9px] font-bold"
                    style={{
                      backgroundColor: 'rgba(59, 130, 246, 0.15)',
                      color: '#3b82f6',
                      border: '1px solid rgba(59, 130, 246, 0.4)',
                    }}
                  >
                    ℹ {longHistoryNotice}
                  </span>
                )}
              </h3>
              <select
                value={historyDays}
                onChange={(e) => setHistoryDays(Number(e.target.value))}
                className="bg-[var(--bg-primary)] border border-[var(--border)] rounded px-2 py-1 text-[10px] text-[var(--text-secondary)]"
              >
                <option value={1}>1天</option>
                <option value={3}>3天</option>
                <option value={7}>7天</option>
                <option value={14}>14天</option>
                <option value={30}>30天</option>
              </select>
            </div>
            {histLoading ? (
              <div className="text-xs text-[var(--text-secondary)] p-8 text-center">加载中...</div>
            ) : historyData.length === 0 ? (
              <div className="text-xs text-[var(--text-secondary)] p-8 text-center">
                暂无历史数据
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="90%">
                <ComposedChart data={historyData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.5} />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10, fill: 'var(--text-secondary)' }}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 10, fill: 'var(--text-secondary)' }}
                    tickFormatter={(v: number) => (Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : v.toFixed(0))}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 10, fill: 'var(--text-secondary)' }}
                    tickFormatter={(v: number) => v.toFixed(0)}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      borderRadius: '8px',
                      fontSize: '12px',
                      color: 'var(--text-primary)',
                    }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: '11px', color: 'var(--text-secondary)' }}
                  />
                  {/* Net GEX 柱状图 */}
                  <Bar
                    yAxisId="left"
                    dataKey="net_gex"
                    name="Net GEX"
                    radius={[1, 1, 0, 0]}
                  >
                    {historyData.map((entry, idx) => (
                      <Cell
                        key={idx}
                        fill={(entry.net_gex ?? 0) >= 0 ? POS_GAMMA : NEG_GAMMA}
                      />
                    ))}
                  </Bar>
                  {/* 现货价格线 */}
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="spot_price"
                    name="Spot Price"
                    stroke="var(--accent-blue)"
                    dot={false}
                    strokeWidth={2}
                  />
                  {/* 零轴加粗 */}
                  <ReferenceLine
                    yAxisId="left"
                    y={0}
                    stroke="var(--text-secondary)"
                    strokeWidth={2}
                    opacity={0.8}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      {/* ═══ 底部: 关键价位汇总表 ═══ */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 shrink-0">
        <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-3">
          关键价位 — {selectedSymbol}
        </h3>
        {lvlsLoading ? (
          <div className="text-xs text-[var(--text-secondary)] p-2">加载中...</div>
        ) : !levels ? (
          <div className="text-xs text-[var(--text-secondary)] p-2">暂无数据</div>
        ) : (
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
            <KeyLevelCard
              label="Zero Gamma"
              value={levels.zero_gamma_level}
              color={ZERO_GAMMA}
              highlight={spotPriceDeviation !== null}
              deviation={spotPriceDeviation}
            />
            <KeyLevelCard
              label="Call Wall"
              value={levels.call_wall}
              color={POS_GAMMA}
            />
            <KeyLevelCard
              label="Put Wall"
              value={levels.put_wall}
              color={NEG_GAMMA}
            />
            <KeyLevelCard
              label="Net GEX"
              value={levels.net_gex}
              color={levels.net_gex != null && levels.net_gex >= 0 ? POS_GAMMA : NEG_GAMMA}
              isGEX
            />
            <KeyLevelCard
              label="Spot Price"
              value={levels.spot_price}
              color="var(--accent-blue)"
            />
            <div className="bg-[var(--bg-primary)] rounded-lg p-3 flex flex-col items-center justify-center">
              <span className="text-[10px] text-[var(--text-secondary)] mb-1">数据时间</span>
              <span className="text-[9px] text-[var(--text-secondary)] text-center">
                {levels.timestamp ? formatTime(levels.timestamp, timezone) : '--'}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 关键价位卡片
// ═══════════════════════════════════════════════════════════════
function KeyLevelCard({
  label,
  value,
  color,
  highlight,
  deviation,
  isGEX,
}: {
  label: string
  value: number | null
  color: string
  highlight?: boolean
  deviation?: number | null
  isGEX?: boolean
}) {
  return (
    <div
      className="bg-[var(--bg-primary)] rounded-lg p-3 flex flex-col items-center justify-center"
      style={highlight ? { border: `1px solid ${color}40` } : {}}
    >
      <span className="text-[10px] text-[var(--text-secondary)] mb-1">{label}</span>
      <span className="text-sm font-bold" style={{ color }}>
        {value != null
          ? isGEX
            ? formatGEX(value)
            : value.toFixed(0)
          : '--'}
      </span>
      {deviation != null && (
        <span
          className="text-[9px] mt-0.5"
          style={{ color: deviation >= 0 ? POS_GAMMA : NEG_GAMMA }}
        >
          {deviation >= 0 ? '+' : ''}{deviation.toFixed(1)}% 偏离
        </span>
      )}
    </div>
  )
}
