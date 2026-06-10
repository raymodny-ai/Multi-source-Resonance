import { useMemo } from 'react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'

interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  positive?: boolean // true: green, false: red
}

/**
 * 微缩折线图组件 (PRD §6.8)
 * 用于移动端卡片中展示 7 天趋势形态
 * 无坐标轴、无网格线、纯折线
 */
export default function Sparkline({
  data,
  height = 40,
  positive = true,
}: SparklineProps) {
  const chartData = useMemo(
    () => data.map((value, i) => ({ i, value })),
    [data],
  )

  const color = positive ? '#22c55e' : '#ef4444'
  const min = Math.min(...data)
  const max = Math.max(...data)
  const padding = (max - min) * 0.1 || 1

  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/**
 * 横屏模式提示横幅组件
 */
export function LandscapeHint() {
  return (
    <div className="md:hidden flex items-center justify-center gap-2 py-2 px-3 mt-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[10px] text-[var(--text-secondary)]">
      <span className="inline-block text-base">↻</span>
      横置手机查看完整交互式图表
    </div>
  )
}
