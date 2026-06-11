import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { CrossAssetHeatmap as CrossAssetHeatmapData } from '../types/api'

interface CrossAssetHeatmapProps {
  data?: CrossAssetHeatmapData
  isLoading?: boolean
}

const ASSET_COLORS: Record<string, string> = {
  GEX: '#3b82f6',
  VIX: '#8b5cf6',
  Crypto: '#f59e0b',
  Darkpool: '#10b981',
}

export default function CrossAssetHeatmap({ data, isLoading }: CrossAssetHeatmapProps) {
  const option = useMemo(() => {
    if (!data?.matrix || !data?.assets) return {}

    const { assets, matrix, signals } = data

    // Build heatmap data: [colIdx, rowIdx, value]
    const heatData: [number, number, number][] = []
    for (let i = 0; i < assets.length; i++) {
      for (let j = 0; j < assets.length; j++) {
        heatData.push([j, i, matrix[i][j]])
      }
    }

    return {
      tooltip: {
        position: 'top',
        formatter: (params: { value: number[] }) => {
          const [col, row, val] = params.value
          const a = assets[col]
          const b = assets[row]
          const desc = val > 0.3 ? '强共振 ↑' : val > 0 ? '弱共振 ↗' : val > -0.3 ? '分歧 →' : '强背离 ↓'
          return `${a} × ${b}<br/>一致性: <b>${(val * 100).toFixed(0)}%</b><br/>${desc}`
        },
      },
      grid: {
        left: '12%',
        right: '10%',
        top: '5%',
        bottom: '15%',
      },
      xAxis: {
        type: 'category',
        data: assets,
        splitArea: { show: true },
        axisLabel: {
          color: '#94a3b8',
          fontSize: 11,
          fontWeight: 'bold',
        },
      },
      yAxis: {
        type: 'category',
        data: assets,
        splitArea: { show: true },
        axisLabel: {
          color: '#94a3b8',
          fontSize: 11,
          fontWeight: 'bold',
        },
      },
      visualMap: {
        min: -1,
        max: 1,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        itemWidth: 12,
        itemHeight: 100,
        textStyle: { color: '#94a3b8', fontSize: 10 },
        inRange: {
          color: ['#ef4444', '#1e1b4b', '#1e293b', '#064e3b', '#22c55e'],
        },
      },
      series: [
        {
          name: '方向一致性',
          type: 'heatmap',
          data: heatData,
          label: {
            show: true,
            color: '#e2e8f0',
            fontSize: 12,
            fontWeight: 'bold',
            formatter: (params: { value: number[] }) => {
              const val = params.value[2] as number
              return (val * 100).toFixed(0) + '%'
            },
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowColor: 'rgba(0,0,0,0.5)',
            },
          },
        },
      ],
    }
  }, [data])

  if (isLoading) {
    return (
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-3">跨资产共振热力图</h3>
        <div className="h-[220px] skeleton rounded-lg" />
      </div>
    )
  }

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-[var(--text-primary)]">跨资产共振热力图</h3>
        {data && (
          <span className="text-[10px] text-[var(--text-secondary)]">
            整体一致性: {data.overall_coherence.toFixed(0)}%
          </span>
        )}
      </div>

      {data?.signals && (
        <div className="flex gap-3 mb-2 flex-wrap">
          {data.assets.map((asset, i) => {
            const sig = data.signals[i]
            const color = sig > 0 ? '#22c55e' : sig < 0 ? '#ef4444' : '#94a3b8'
            return (
              <span key={asset} className="text-[10px] flex items-center gap-1">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ASSET_COLORS[asset] ?? '#64748b' }} />
                <span className="text-[var(--text-secondary)]">{asset}:</span>
                <span style={{ color }}>{sig > 0 ? '+' : ''}{sig.toFixed(2)}</span>
              </span>
            )
          })}
        </div>
      )}

      <ReactECharts
        option={option}
        style={{ height: 220 }}
        opts={{ renderer: 'svg' }}
        notMerge
      />
    </div>
  )
}
