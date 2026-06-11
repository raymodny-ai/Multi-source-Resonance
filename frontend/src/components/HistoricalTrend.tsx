import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { ResonanceHistoryPoint } from '../types/api'
import { ALERT_LEVEL_COLORS } from '../types/common'
import type { AlertLevel } from '../types/common'

interface HistoricalTrendProps {
  data?: ResonanceHistoryPoint[]
  isLoading?: boolean
}

export default function HistoricalTrend({ data, isLoading }: HistoricalTrendProps) {
  const option = useMemo(() => {
    if (!data || data.length === 0) return {}

    const timestamps = data.map((d) => {
      const ts = d.timestamp
      return ts.length > 16 ? ts.slice(5, 16) : ts
    })

    const scores = data.map((d) => d.total_score)
    const levels = data.map((d) => d.alert_level)

    // 阈值线
    const thresholdLine = (value: number, label: string, color: string) => ({
      name: label,
      type: 'line' as const,
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color, type: 'dashed' as const, width: 1 },
        data: [{ yAxis: value, label: { formatter: label, fontSize: 9, color: '#94a3b8' } }],
      },
      data: [],
    })

    return {
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,0.95)',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 11 },
        formatter: (params: { name: string; value: number; color: string }[]) => {
          if (!params?.length) return ''
          const p = params[0]
          const idx = data.findIndex((d) => (d.timestamp.length > 16 ? d.timestamp.slice(5, 16) : d.timestamp) === p.name)
          const level = idx >= 0 ? levels[idx] : 'NO_SIGNAL'
          const color = ALERT_LEVEL_COLORS[level as AlertLevel] ?? '#64748b'
          return `<div style="font-size:11px;margin-bottom:4px">${p.name}</div>
            <div style="display:flex;justify-content:space-between;gap:12px">
              <span>共振得分</span>
              <span style="color:${p.color};font-weight:bold">${p.value.toFixed(2)}</span>
            </div>
            <div style="margin-top:2px">
              <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${color};margin-right:4px"></span>
              <span style="font-size:10px;color:#94a3b8">${level.replace('_', ' ')}</span>
            </div>`
        },
      },
      grid: {
        left: '8%',
        right: '5%',
        top: '8%',
        bottom: '8%',
      },
      xAxis: {
        type: 'category',
        data: timestamps,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#64748b', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 5.5,
        interval: 1,
        axisLabel: { color: '#64748b', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: [
        {
          name: '共振得分',
          type: 'line',
          data: scores,
          smooth: true,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: '#8b5cf6', width: 2 },
          itemStyle: {
            color: (params: { dataIndex: number }) => {
              const level = levels[params.dataIndex]
              return ALERT_LEVEL_COLORS[level as AlertLevel] ?? '#64748b'
            },
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(139,92,246,0.2)' },
                { offset: 1, color: 'rgba(139,92,246,0)' },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [
              { yAxis: 3.5, lineStyle: { color: '#ef4444', type: 'dashed', width: 1 }, label: { formatter: 'LEVEL 3', fontSize: 9, color: '#ef4444' } },
              { yAxis: 3.0, lineStyle: { color: '#eab308', type: 'dashed', width: 1 }, label: { formatter: 'LEVEL 2', fontSize: 9, color: '#eab308' } },
              { yAxis: 2.0, lineStyle: { color: '#f59e0b', type: 'dashed', width: 1 }, label: { formatter: 'LEVEL 1', fontSize: 9, color: '#f59e0b' } },
            ],
          },
        },
      ],
    }
  }, [data])

  if (isLoading) {
    return (
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-3">共振历史趋势</h3>
        <div className="h-[200px] skeleton rounded-lg" />
      </div>
    )
  }

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
      <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-2">共振历史趋势</h3>
      <ReactECharts
        option={option}
        style={{ height: 200 }}
        opts={{ renderer: 'svg' }}
        notMerge
      />
    </div>
  )
}
