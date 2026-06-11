import { useMemo } from 'react'
import type { ResonanceResult } from '../types/api'
import { ALERT_LEVEL_COLORS } from '../types/common'

interface ResonanceGaugeProps {
  resonance: ResonanceResult
  className?: string
}

export default function ResonanceGauge({ resonance, className = '' }: ResonanceGaugeProps) {
  const { total_score, max_score, alert_level, resonance_pct } = resonance
  const pct = Math.min(resonance_pct, 100)
  const color = ALERT_LEVEL_COLORS[alert_level] ?? '#64748b'
  const isActive = alert_level !== 'NO_SIGNAL'

  // SVG arc parameters
  const radius = 68
  const strokeWidth = 10
  const circumference = 2 * Math.PI * radius
  const progress = (pct / 100) * circumference * 0.75  // 270° arc
  const rotation = 135  // start from bottom-left

  const dashOffset = useMemo(() => circumference - progress, [circumference, progress])

  // Tick marks every 25%
  const ticks = [0, 25, 50, 75, 100]

  return (
    <div className={`bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 ${className}`}>
      <h3 className="text-xs font-semibold text-[var(--text-primary)] mb-3">共振仪表盘</h3>

      <div className="relative w-full max-w-[220px] mx-auto">
        {/* Gauge SVG */}
        <svg viewBox="0 0 180 120" className="w-full">
          {/* Background arc */}
          <path
            d="M 20 110 A 68 68 0 0 1 160 110"
            fill="none"
            stroke="var(--border)"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />

          {/* Progress arc */}
          <path
            d="M 20 110 A 68 68 0 0 1 160 110"
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{
              transition: 'stroke-dashoffset 0.8s ease, stroke 0.5s ease',
              transform: `rotate(${rotation}deg)`,
              transformOrigin: '90px 110px',
            }}
          />

          {/* Tick marks */}
          {ticks.map((tick) => {
            const angle = ((tick / 100) * 270 - 135) * (Math.PI / 180)
            const x1 = 90 + 55 * Math.cos(angle)
            const y1 = 110 + 55 * Math.sin(angle)
            const x2 = 90 + 65 * Math.cos(angle)
            const y2 = 110 + 65 * Math.sin(angle)
            return (
              <g key={tick}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--text-secondary)" strokeWidth="1" />
                <text
                  x={90 + 48 * Math.cos(angle)}
                  y={110 + 48 * Math.sin(angle)}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className="fill-[var(--text-secondary)]"
                  fontSize="7"
                >
                  {tick}
                </text>
              </g>
            )
          })}

          {/* Needle */}
          <line
            x1={90}
            y1={110}
            x2={90 + 60 * Math.cos(((pct / 100) * 270 - 135) * (Math.PI / 180))}
            y2={110 + 60 * Math.sin(((pct / 100) * 270 - 135) * (Math.PI / 180))}
            stroke={color}
            strokeWidth="2"
            strokeLinecap="round"
            style={{ transition: 'all 0.8s ease' }}
          />
          <circle cx="90" cy="110" r="3" fill={color} />
        </svg>

        {/* Center value */}
        <div className="absolute bottom-2 left-1/2 -translate-x-1/2 text-center">
          <div className="text-2xl font-bold" style={{ color }}>
            {total_score.toFixed(1)}
          </div>
          <div className="text-[10px] text-[var(--text-secondary)]">/ {max_score.toFixed(1)}</div>
        </div>
      </div>

      {/* Level badge */}
      <div className="flex items-center justify-between mt-2 px-2">
        <span
          className="text-[10px] px-2 py-0.5 rounded-full font-bold"
          style={{ backgroundColor: `${color}20`, color }}
        >
          {alert_level === 'NO_SIGNAL' ? '无共振' : alert_level.replace('_', ' ')}
        </span>
        <span className="text-[10px] text-[var(--text-secondary)]">
          {resonance_pct.toFixed(0)}%
        </span>
      </div>

      {/* Pulse animation for active signal */}
      {isActive && (
        <div className="mt-2 text-center">
          <span
            className="inline-block w-2 h-2 rounded-full animate-pulse"
            style={{ backgroundColor: color }}
          />
        </div>
      )}
    </div>
  )
}
