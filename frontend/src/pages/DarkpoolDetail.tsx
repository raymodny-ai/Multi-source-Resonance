import { useState, useMemo } from 'react'
import { useDarkpoolHistory } from '../api/darkpool'
import { formatPercent, formatDecimal } from '../utils/format'
import type { DarkpoolHistoryPoint } from '../types/api'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from 'recharts'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import * as echarts from 'echarts/core'
import { LineChart as ELineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkPointComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([ELineChart, GridComponent, TooltipComponent, MarkPointComponent, CanvasRenderer])

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

  const { data: historyData, isLoading } = useDarkpoolHistory(range)

  // Use mock data if backend not available
  const chartData = useMemo(() => {
    if (historyData && historyData.length > 0) return historyData
    return generateMockData(range)
  }, [historyData, range])

  const latest = chartData[chartData.length - 1]

  const stockgridOption = useMemo(() => ({
    backgroundColor: 'transparent',
    grid: { top: 20, right: 20, bottom: 40, left: 50 },
    xAxis: {
      type: 'category' as const,
      data: chartData.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8', fontSize: 10 },
    },
    yAxis: {
      type: 'value' as const,
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8', fontSize: 10, formatter: (v: number) => v.toFixed(4) },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: [
      {
        name: '20d Slope',
        type: 'line',
        data: chartData.map((d) => d.stockgrid_20d_slope),
        smooth: true,
        lineStyle: { color: '#22c55e', width: 1.5 },
        itemStyle: { color: '#22c55e' },
        symbol: 'none',
        markPoint: {
          data: chartData
            .map((d, i) => (d.divergence_flag ? { coord: [i, d.stockgrid_20d_slope], value: '底背离', symbol: 'triangle', symbolRotate: 180, itemStyle: { color: '#ef4444' } } : null))
            .filter(Boolean),
        },
      },
      {
        name: '60d Slope',
        type: 'line',
        data: chartData.map((d) => d.stockgrid_60d_slope),
        smooth: true,
        lineStyle: { color: '#3b82f6', width: 1.5 },
        itemStyle: { color: '#3b82f6' },
        symbol: 'none',
        markPoint: {
          data: chartData
            .map((d, i) => (d.golden_cross_flag ? { coord: [i, d.stockgrid_20d_slope], value: 'GC', symbol: 'pin', itemStyle: { color: '#eab308' } } : null))
            .filter(Boolean),
        },
      },
    ],
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: '#1e293b',
      borderColor: '#334155',
      textStyle: { color: '#f1f5f9', fontSize: 11 },
    },
  }), [chartData])

  if (isLoading && !historyData) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">暗盘数据详情</h1>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-64 rounded-xl skeleton" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4 max-w-[1600px]">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">暗盘数据详情</h1>
        {/* Range selector */}
        <div className="flex gap-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-0.5">
          {([30, 60, 90, 120] as RangeOption[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
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

      {/* DIX + Short Volume charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* DIX Chart */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">DIX 暗盘买入强度</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                tickFormatter={(v: string) => v.slice(5)}
                stroke="#334155"
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                stroke="#334155"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  fontSize: '12px',
                  color: '#f1f5f9',
                }}
                labelFormatter={(lbl: unknown) => String(lbl)}
                formatter={(value: unknown) => [`${Number(value).toFixed(1)}%`, 'DIX']}
              />
              <ReferenceLine
                y={45}
                stroke="#ef4444"
                strokeDasharray="5 5"
                label={{ value: '45%', fill: '#ef4444', fontSize: 10, position: 'right' }}
              />
              <Line
                type="monotone"
                dataKey="dix_value"
                stroke="#22c55e"
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 4, fill: '#22c55e' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Short Volume Chart */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">Short Volume 卖空比</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                tickFormatter={(v: string) => v.slice(5)}
                stroke="#334155"
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                stroke="#334155"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  fontSize: '12px',
                  color: '#f1f5f9',
                }}
                formatter={(value: unknown) => [`${Number(value).toFixed(1)}%`, 'Short Vol']}
              />
              <ReferenceLine
                y={45}
                stroke="#ef4444"
                strokeDasharray="5 5"
                label={{ value: '45%', fill: '#ef4444', fontSize: 10, position: 'right' }}
              />
              <Line
                type="monotone"
                dataKey="chartexchange_short_ratio"
                stroke="#eab308"
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 4, fill: '#eab308' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Stockgrid Net Position Chart */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3">Stockgrid 净头寸趋势 + 背离标注</h3>
        <ReactEChartsCore
          echarts={echarts}
          option={stockgridOption}
          style={{ height: 300 }}
          notMerge
        />
        <div className="flex items-center gap-4 mt-2 text-[10px] text-[var(--text-secondary)]">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#22c55e]" /> 20d Slope
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#3b82f6]" /> 60d Slope
          </span>
          <span className="flex items-center gap-1">
            <span className="text-[10px] text-[#ef4444]">▲</span> 底背离
          </span>
          <span className="flex items-center gap-1">
            <span className="text-[10px] text-[#eab308]">◆</span> Golden Cross
          </span>
        </div>
      </div>

      {/* Summary Card */}
      {latest && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">指标摘要</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {[
              { label: 'DIX', value: formatPercent(latest.dix_value), status: latest.dix_value > 45 },
              { label: 'Short Vol', value: formatPercent(latest.chartexchange_short_ratio), status: latest.chartexchange_short_ratio > 45 },
              { label: '20d Slope', value: formatDecimal(latest.stockgrid_20d_slope, 4), status: latest.stockgrid_20d_slope > 0 },
              { label: '60d Slope', value: formatDecimal(latest.stockgrid_60d_slope, 4), status: latest.stockgrid_60d_slope > 0 },
              { label: '底背离', value: latest.divergence_flag ? 'YES' : 'NO', status: latest.divergence_flag },
              { label: 'Golden Cross', value: latest.golden_cross_flag ? 'YES' : 'NO', status: latest.golden_cross_flag },
              { label: '数据日期', value: latest.date, status: true },
            ].map((item) => (
              <div key={item.label} className="text-center">
                <p className="text-[10px] text-[var(--text-secondary)] mb-1">{item.label}</p>
                <p className={`text-xs font-semibold ${item.status ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>
                  {item.value}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
