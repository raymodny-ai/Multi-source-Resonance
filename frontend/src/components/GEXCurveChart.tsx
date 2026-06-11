import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { GEXCurve } from '../types/api'
import { formatCurrency } from '../utils/format'

interface GEXCurveChartProps {
  data?: GEXCurve
  isLoading?: boolean
}

export default function GEXCurveChart({ data, isLoading }: GEXCurveChartProps) {
  const option = useMemo(() => {
    if (!data?.timestamps || data.timestamps.length === 0) return {}

    const timestamps = data.timestamps.map((ts: string) =>
      ts.length > 16 ? ts.slice(5, 16) : ts
    )

    return {
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,23,42,0.95)',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 11 },
        formatter: (params: { name: string; seriesName: string; value: number; color: string }[]) => {
          if (!params?.length) return ''
          let html = `<div style="font-size:11px;margin-bottom:4px">${params[0].name}</div>`
          params.forEach((p) => {
            html += `<div style="display:flex;justify-content:space-between;gap:12px">
              <span>${p.seriesName}</span>
              <span style="color:${p.color};font-weight:bold">${formatCurrency(p.value)}</span>
            </div>`
          })
          return html
        },
      },
      legend: {
        data: ['GEX 校准值', 'Put Wall', 'Flip Zone 下界', 'Flip Zone 上界'],
        bottom: 0,
        textStyle: { color: '#94a3b8', fontSize: 10 },
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: {
        left: '8%',
        right: '5%',
        top: '5%',
        bottom: '15%',
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
        axisLabel: {
          color: '#64748b',
          fontSize: 10,
          formatter: (v: number) => (v / 1e6).toFixed(0) + 'M',
        },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: [
        {
          name: 'GEX 校准值',
          type: 'line',
          data: data.gex_calibrated,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#3b82f6', width: 2 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(59,130,246,0.25)' },
                { offset: 1, color: 'rgba(59,130,246,0)' },
              ],
            },
          },
        },
        {
          name: 'Put Wall',
          type: 'line',
          data: data.put_wall_level,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#ef4444', width: 1.5, type: 'dashed' },
        },
        {
          name: 'Flip Zone 下界',
          type: 'line',
          data: data.flip_zone_lower,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#22c55e', width: 1, type: 'dotted' },
        },
        {
          name: 'Flip Zone 上界',
          type: 'line',
          data: data.flip_zone_upper,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#22c55e', width: 1, type: 'dotted' },
        },
      ],
    }
  }, [data])

  if (isLoading) {
    return (
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-3">GEX 曲线</h3>
        <div className="h-[220px] skeleton rounded-lg" />
      </div>
    )
  }

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
      <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-2">GEX 曲线</h3>
      <ReactECharts
        option={option}
        style={{ height: 220 }}
        opts={{ renderer: 'svg' }}
        notMerge
      />
    </div>
  )
}
