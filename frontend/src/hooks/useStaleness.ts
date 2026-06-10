import { useMemo, useEffect } from 'react'
import { STALENESS_THRESHOLDS } from '../types/common'
import type { StalenessLevel, StalenessInfo } from '../types/common'

/**
 * 根据 lastUpdatedAt 时间戳计算数据陈旧度
 * @param lastUpdatedAt - 最后更新时间 (毫秒时间戳)
 * @returns StalenessInfo { level, label, className }
 */
export function useStaleness(lastUpdatedAt: number | null | undefined): StalenessInfo {
  const info = useMemo<StalenessInfo>(() => {
    if (!lastUpdatedAt) {
      return { level: 'FRESH', label: '', className: '' }
    }
    const elapsed = (Date.now() - lastUpdatedAt) / 1000

    if (elapsed >= STALENESS_THRESHOLDS.STALE_MAX) {
      const mins = Math.floor(elapsed / 60)
      return {
        level: 'DISCONNECTED',
        label: `数据中断 ${mins} 分钟`,
        className: 'disconnected',
      }
    }
    if (elapsed >= STALENESS_THRESHOLDS.STALE_WARN_MAX) {
      const mins = Math.floor(elapsed / 60)
      return {
        level: 'STALE',
        label: `上次更新: ${mins} 分钟前`,
        className: 'stale-card',
      }
    }
    if (elapsed >= STALENESS_THRESHOLDS.FRESH_MAX) {
      return {
        level: 'STALE_WARN',
        label: `${Math.floor(elapsed)}秒前`,
        className: 'stale-warn',
      }
    }
    return { level: 'FRESH', label: '● LIVE', className: '' }
  }, [lastUpdatedAt])

  return info
}

/**
 * 定期刷新 staleness 状态的 Hook
 * 每 5 秒触发一次重新计算
 */
export function useStalenessUpdater(
  lastUpdatedAt: number | null | undefined,
  onUpdate: () => void,
) {
  useEffect(() => {
    if (lastUpdatedAt == null) return
    const timer = setInterval(onUpdate, 5000)
    return () => clearInterval(timer)
  }, [lastUpdatedAt, onUpdate])
}
