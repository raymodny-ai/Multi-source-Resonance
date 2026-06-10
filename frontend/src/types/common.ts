// ============ 共享枚举与常量 ============

export type AlertLevel = 'LEVEL_1' | 'LEVEL_2' | 'LEVEL_3' | 'NO_SIGNAL'

export type StalenessLevel = 'FRESH' | 'STALE_WARN' | 'STALE' | 'DISCONNECTED'

export type TimezoneOption = 'America/New_York' | 'UTC' | 'local'

export interface StalenessInfo {
  level: StalenessLevel
  label: string
  className: string
}

export const ALERT_LEVEL_COLORS: Record<AlertLevel, string> = {
  LEVEL_3: '#ef4444',
  LEVEL_2: '#eab308',
  LEVEL_1: '#f59e0b',
  NO_SIGNAL: '#64748b',
}

export const ALERT_LEVEL_LABELS: Record<AlertLevel, string> = {
  LEVEL_3: 'LEVEL 3',
  LEVEL_2: 'LEVEL 2',
  LEVEL_1: 'LEVEL 1',
  NO_SIGNAL: '无信号',
}

export const STATE_COLORS: Record<string, string> = {
  POSITIVE: '#22c55e',
  CONTANGO: '#22c55e',
  FLIP_ON: '#22c55e',
  CLEANUP_COMPLETE: '#22c55e',
  CLEANUP_PENDING: '#eab308',
  STRONG_ACCUMULATION: '#22c55e',
  TRIGGERED_3OF3: '#22c55e',
  TRIGGERED_2OF3: '#eab308',
  CONVERGING: '#eab308',
  NEUTRAL: '#64748b',
  NORMAL: '#64748b',
  NEGATIVE: '#ef4444',
  BACKWARDATION: '#ef4444',
  LEVERAGE_BUILDUP: '#ef4444',
}

export const HAWKES_STATE_COLORS: Record<string, string> = {
  SUBCRITICAL: '#22c55e',
  CRITICAL: '#eab308',
  SUPERCRITICAL: '#ef4444',
}

export const HAWKES_STATE_LABELS: Record<string, string> = {
  SUBCRITICAL: '亚临界衰竭',
  CRITICAL: '临界区',
  SUPERCRITICAL: '超临界自激',
}

export const TIMEZONE_OPTIONS: { value: TimezoneOption; label: string }[] = [
  { value: 'America/New_York', label: 'EST/EDT (美东)' },
  { value: 'UTC', label: 'UTC' },
  { value: 'local', label: 'Local (本地)' },
]

// 数据陈旧度阈值 (秒)
export const STALENESS_THRESHOLDS = {
  FRESH_MAX: 30,
  STALE_WARN_MAX: 120,
  STALE_MAX: 300,
} as const
