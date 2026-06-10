import { useState, useMemo } from 'react'
import { useDarkpoolHistory } from '../api/darkpool'
import { useTickers } from '../api/tickers'
import { formatPercent, formatDecimal } from '../utils/format'
import type { DarkpoolHistoryPoint, TickerInfo } from '../types/api'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkPointComponent, MarkLineComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ChevronDown } from 'lucide-react'

echarts.use([LineChart, GridComponent, TooltipComponent, MarkPointComponent, MarkLineComponent, DataZoomComponent, LegendComponent, CanvasRenderer])

type RangeOption = 30 | 60 | 90 | 120

function generateMockData(days: number): DarkpoolHistoryPoint[] {
  const data: DarkpoolHistoryPoint[] = []
  const now = new Date()
  for (let i = days; i >= 0; i--) {
    const d = new Date(now)
    d.setDate(d.getDate() - i)
    const base = 40 + Math.sin(i * 0.15) * 8
    data.push({
      date: d.toISOString().split('T')[0],
      dix_value: base + Math.random() * 4,
      chartexchange_short_ratio: base + 1 + Math.random() * 3,
      stockgrid_20d_slope: Math.sin(i * 0.12) * 0.003,
      stockgrid_60d_slope: Math.sin(i * 0.08) * 0.0025,
      divergence_flag: i % 15 === 0,
      golden_cross_flag: i % 20 === 0,
    })
  }
  return data
}

export default function DarkpoolDetail() {
  const [range, setRange] = useState<RangeOption>(90)
  const [ticker, setTicker] = useState('SPY')
  const [showTickerMenu, setShowTickerMenu] = useState(false)

  const { data: tickers } = useTickers()
  const { data: historyData, isLoading } = useDarkpoolHistory(range)

  const chartData = useMemo(() => {
    if (historyData && historyData.length > 0) return historyData
    return generateMockData(range)
  }, [historyData, range])

  const latest = chartData[chartData.length - 1]
  const dateLabels = chartData.map((d) => d.date.slice(5))

  const currentTicker = tickers?.find((t) => t.symbol === ticker) ?? { symbol: 'SPY', name: 'S&P 500 ETF' }

  // --- DIX Chart Option ---
  const dixOption = useMemo(() => {
    const threshold = 45
    const aboveThreshold = chartData.map((d, i) => d.dix_value > threshold ? { coord: [i, d.dix_value], value: d.dix_value.toFixed(1), symbol: 'pin', symbolSize: 8, itemStyle: { color: '#ef4444' } } : null).filter(Boolean)
    return {
      backgroundColor: 'transparent',
      grid: { top: 20, right: 30, bottom: 50, left: 45 },
      xAxis: { type: 'category' as const, data: dateLabels, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#94a3b8', fontSize: 9, rotate: 45, interval: Math.floor(dateLabels.length / 8) } },
      yAxis: { type: 'value' as const, min: 0, max: 100, axisLabel: { color: '#94a3b8', fontSize: 10, formatter: '{value}%' }, splitLine: { lineStyle: { color: '#1e293b' } } },
      series: [{
        name: 'DIX', type: 'line', data: chartData.map((d) => d.dix_value), smooth: true,
        lineStyle: { color: '#22c55e', width: 2 }, itemStyle: { color: '#22c55e' }, symbol: 'none',
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#ef4444', type: 'dashed', width: 1.5 },
          data: [{ yAxis: threshold, label: { formatter: '45%', color: '#ef4444', fontSize: 10, position: 'end' } }] },
        markPoint: { symbol: 'pin', symbolSize: 8, data: aboveThreshold },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(34,197,94,0.15)' }, { offset: 1, color: 'rgba(34,197,94,0)' }
        ])},
      }],
      tooltip: { trigger: 'axis' as const, backgroundColor: '#1e293b', borderColor: '#334155', textStyle: { color: '#f1f5f9', fontSize: 11 },
        formatter: (params: unknown) => {
          const p = (params as Array<{ dataIndex: number; value: number }>)[0]
          return `<b>${dateLabels[p.dataIndex]}</b><br/>DIX: ${p.value.toFixed(1)}%${p.value > threshold ? ' ⚠️' : ''}`
        }},
      dataZoom: [{ type: 'inside', start: Math.max(0, 100 - (90 / range) * 100), end: 100 }],
    }
  }, [chartData, dateLabels, range])

  // --- Short Volume Chart Option ---
  const shortVolumeOption = useMemo(() => ({
    backgroundColor: 'transparent',
    grid: { top: 20, right: 30, bottom: 50, left: 45 },
    xAxis: { type: 'category' as const, data: dateLabels, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#94a3b8', fontSize: 9, rotate: 45, interval: Math.floor(dateLabels.length / 8) } },
    yAxis: { type: 'value' as const, min: 0, max: 100, axisLabel: { color: '#94a3b8', fontSize: 10, formatter: '{value}%' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    series: [{
      name: 'Short Volume', type: 'line', data: chartData.map((d) => d.chartexchange_short_ratio), smooth: true,
      lineStyle: { color: '#eab308', width: 2 }, itemStyle: { color: '#eab308' }, symbol: 'none',
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#ef4444', type: 'dashed', width: 1.5 },
        data: [{ yAxis: 45, label: { formatter: '45%', color: '#ef4444', fontSize: 10, position: 'end' } }] },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(234,179,8,0.15)' }, { offset: 1, color: 'rgba(234,179,8,0)' }
      ])},
    }],
    tooltip: { trigger: 'axis' as const, backgroundColor: '#1e293b', borderColor: '#334155', textStyle: { color: '#f1f5f9', fontSize: 11 } },
    dataZoom: [{ type: 'inside', start: Math.max(0, 100 - (90 / range) * 100), end: 100 }],
  }), [chartData, dateLabels, range])

  // --- Stockgrid Chart Option ---
  const stockgridOption = useMemo(() => {
    const divergences = chartData
      .map((d, i) => d.divergence_flag ? { coord: [i, d.stockgrid_20d_slope], value: '底背离', symbol: 'triangle', symbolRotate: 180, symbolSize: 10, itemStyle: { color: '#ef4444' } } : null)
      .filter(Boolean)
    const goldenCrosses = chartData
      .map((d, i) => d.golden_cross_flag ? { coord: [i, d.stockgrid_20d_slope], value: 'GC', symbol: 'diamond', symbolSize: 10, itemStyle: { color: '#f59e0b' } } : null)
      .filter(Boolean)
    return {
      backgroundColor: 'transparent',
      grid: { top: 20, right: 30, bottom: 60, left: 60 },
      legend: { data: ['20d Slope', '60d Slope'], textStyle: { color: '#94a3b8', fontSize: 10 }, bottom: 5 },
      xAxis: { type: 'category' as const, data: dateLabels, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#94a3b8', fontSize: 9, rotate: 45, interval: Math.floor(dateLabels.length / 8) } },
      yAxis: { type: 'value' as const, axisLabel: { color: '#94a3b8', fontSize: 10, formatter: (v: number) => v.toFixed(4) }, splitLine: { lineStyle: { color: '#1e293b' } } },
      series: [
        {
          name: '20d Slope', type: 'line', data: chartData.map((d) => d.stockgrid_20d_slope), smooth: true,
          lineStyle: { color: '#22c55e', width: 1.5 }, itemStyle: { color: '#22c55e' }, symbol: 'none',
          markPoint: { data: [...divergences, ...goldenCrosses] },
        },
        {
          name: '60d Slope', type: 'line', data: chartData.map((d) => d.stockgrid_60d_slope), smooth: true,
          lineStyle: { color: '#3b82f6', width: 1.5, type: 'dashed' }, itemStyle: { color: '#3b82f6' }, symbol: 'none',
        },
      ],
      tooltip: { trigger: 'axis' as const, backgroundColor: '#1e293b', borderColor: '#334155', textStyle: { color: '#f1f5f9', fontSize: 11 } },
      dataZoom: [{ type: 'inside', start: Math.max(0, 100 - (120 / range) * 100), end: 100 }],
    }
  }, [chartData, dateLabels, range])

  if (isLoading && !historyData) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">暗盘数据详情</h1>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {[1, 2, 3].map((i) => (<div key={i} className="h-72 rounded-xl skeleton" />))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 max-w-[1600px]">
      {/* Header with ticker selector */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold">暗盘数据详情</h1>
        <div className="flex items-center gap-3">
          {/* Ticker Selector */}
          <div className="relative">
            <button
              onClick={() => setShowTickerMenu(!showTickerMenu)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] text-sm text-[var(--text-primary)] hover:border-white/20 transition-colors min-w-[120px]"
            >
              <span className="font-bold">{currentTicker.symbol}</span>
              <span className="text-xs text-[var(--text-secondary)] hidden sm:inline">{currentTicker.name}</span>
              <ChevronDown size={14} className="text-[var(--text-secondary)]" />
            </button>
            {showTickerMenu && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowTickerMenu(false)} />
                <div className="absolute top-full mt-1 right-0 w-44 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg shadow-xl z-50 py-1">
                  {(tickers ?? [
                    { symbol: 'SPY', name: 'S&P 500 ETF' },
                    { symbol: 'QQQ', name: 'Nasdaq-100 ETF' },
                    { symbol: 'IWM', name: 'Russell 2000 ETF' },
                    { symbol: 'AAPL', name: 'Apple Inc.' },
                    { symbol: 'MSFT', name: 'Microsoft Corp.' },
                    { symbol: 'NVDA', name: 'NVIDIA Corp.' },
                    { symbol: 'TSLA', name: 'Tesla Inc.' },
                    { symbol: 'AMD', name: 'Advanced Micro Devices' },
                  ]).map((t) => (
                    <button
                      key={t.symbol}
                      onClick={() => { setTicker(t.symbol); setShowTickerMenu(false) }}
                      className={`w-full text-left px-3 py-2 text-xs hover:bg-white/5 transition-colors flex items-center gap-2
                        ${ticker === t.symbol ? 'text-[var(--accent-blue)]' : 'text-[var(--text-secondary)]'}`}
                    >
                      <span className="font-bold w-10">{t.symbol}</span>
                      <span>{t.name}</span>
                      {ticker === t.symbol && ' ✓'}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Range selector */}
          <div className="flex gap-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-0.5">
            {([30, 60, 90, 120] as RangeOption[]).map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${r === range ? 'bg-[var(--accent-blue)] text-white' : 'text-[var(--text-secondary)] hover:text-white'}`}
              >
                {r}天
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* DIX + Short Volume Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">DIX 暗盘买入强度（≥45% 高亮）</h3>
          <ReactEChartsCore echarts={echarts} option={dixOption} style={{ height: 280 }} notMerge />
        </div>
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">Short Volume 卖空比</h3>
          <ReactEChartsCore echarts={echarts} option={shortVolumeOption} style={{ height: 280 }} notMerge />
        </div>
      </div>

      {/* Stockgrid Chart */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3">Stockgrid 净头寸趋势 + 背离标注</h3>
        <ReactEChartsCore echarts={echarts} option={stockgridOption} style={{ height: 320 }} notMerge />
        <div className="flex flex-wrap items-center gap-4 mt-2 text-[10px] text-[var(--text-secondary)]">
          <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-[#22c55e] inline-block" /> 20d Slope</span>
          <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-[#3b82f6] inline-block" style={{ borderTop: '1px dashed #3b82f6' }} /> 60d Slope</span>
          <span className="flex items-center gap-1 text-[#ef4444]"><span className="text-xs">▲</span> 底背离</span>
          <span className="flex items-center gap-1 text-[#f59e0b]"><span className="text-xs">◆</span> Golden Cross</span>
        </div>
      </div>

      {/* Summary Card */}
      {latest && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">指标摘要 · {currentTicker.symbol}</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {[
              { label: 'DIX', value: formatPercent(latest.dix_value, 1), status: latest.dix_value > 45, hint: '吸筹线 >45%' },
              { label: 'Short Vol', value: formatPercent(latest.chartexchange_short_ratio, 1), status: latest.chartexchange_short_ratio > 45, hint: '卖空比 >45%' },
              { label: '20d Slope', value: formatDecimal(latest.stockgrid_20d_slope, 4), status: latest.stockgrid_20d_slope > 0, hint: '近20日净头寸斜率' },
              { label: '60d Slope', value: formatDecimal(latest.stockgrid_60d_slope, 4), status: latest.stockgrid_60d_slope > 0, hint: '近60日净头寸斜率' },
              { label: 'DBMF 收复', value: 'YES', status: true, hint: 'DBMF MA5 收复' },
              { label: '底背离', value: latest.divergence_flag ? 'YES' : 'NO', status: latest.divergence_flag, hint: '价格与净头寸背离' },
              { label: 'Golden Cross', value: latest.golden_cross_flag ? 'YES' : 'NO', status: latest.golden_cross_flag, hint: '20d/60d 黄金交叉' },
            ].map((item) => (
              <div key={item.label} className="text-center group relative">
                <p className="text-[10px] text-[var(--text-secondary)] mb-1">{item.label}</p>
                <p className={`text-xs font-semibold ${item.status ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>
                  {item.value}
                </p>
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-0.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded text-[9px] text-[var(--text-secondary)] opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none transition-opacity z-10">
                  {item.hint}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
