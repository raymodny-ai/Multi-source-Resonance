import { useState } from 'react'
import { useStaleness } from '../hooks/useStaleness'
import { STATE_COLORS } from '../types/common'

interface DimensionCardProps {
  title: string
  score: number
  maxScore: number
  state: string
  details: string
  lastUpdatedAt: number
  onClick?: () => void
  children?: React.ReactNode
}

export default function DimensionCard({
  title,
  score,
  maxScore,
  state,
  details,
  lastUpdatedAt,
  onClick,
  children,
}: DimensionCardProps) {
  const [, setTick] = useState(0)
  const { level, label, className } = useStaleness(lastUpdatedAt)

  const pct = maxScore > 0 ? (score / maxScore) * 100 : 0
  const stateColor = STATE_COLORS[state] ?? '#64748b'
  const circumference = 2 * Math.PI * 36
  const dashOffset = circumference - (pct / 100) * circumference

  return (
    <div
      className={`relative bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 cursor-pointer hover:border-white/20 transition-all ${className}`}
      data-stale-label={label}
      onClick={() => {
        // Force re-render for staleness
        setTick((t) => t + 1)
        onClick?.()
      }}
    >
      {/* Staleness indicator */}
      {level !== 'FRESH' && (
        <div className="absolute top-2 right-2 text-[10px] text-[var(--text-secondary)]">
          {label}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ color: stateColor, backgroundColor: `${stateColor}15` }}>
          {state}
        </span>
      </div>

      {/* Score ring + extra info */}
      <div className="flex items-center gap-3">
        {/* Mini ring chart */}
        <div className="relative w-16 h-16 shrink-0">
          <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
            <circle
              cx="40" cy="40" r="36"
              fill="none"
              stroke="var(--border)"
              strokeWidth="6"
            />
            <circle
              cx="40" cy="40" r="36"
              fill="none"
              stroke={stateColor}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              className="transition-all duration-500"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-bold" style={{ color: stateColor }}>
              {score.toFixed(1)}
            </span>
          </div>
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          {children}
        </div>
      </div>

      {/* Details */}
      <p className="mt-2 text-[11px] text-[var(--text-secondary)] leading-relaxed line-clamp-2">
        {details}
      </p>
    </div>
  )
}
