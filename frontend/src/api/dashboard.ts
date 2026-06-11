import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { DashboardScores, CrossAssetHeatmap, ResonanceHistoryPoint, GEXCurve } from '../types/api'

export function useDashboardScores() {
  return useQuery<DashboardScores>({
    queryKey: ['dashboard', 'scores'],
    queryFn: () => get<DashboardScores>('/dashboard/scores'),
    refetchInterval: 30_000, // 30s 自动刷新
  })
}

export function useRecentAlerts(limit = 5) {
  return useQuery<Array<{ id: number; alert_level: string; total_score: number; trigger_time: string; acknowledged: boolean }>>({
    queryKey: ['dashboard', 'recent-alerts', limit],
    queryFn: () => get(`/dashboard/recent-alerts?limit=${limit}`),
    refetchInterval: 30_000,
  })
}

export function useGEXCurve(days = 30) {
  return useQuery<GEXCurve>({
    queryKey: ['dashboard', 'gex-curve', days],
    queryFn: () => get<GEXCurve>(`/dashboard/gex-curve?days=${days}`),
    refetchInterval: 60_000,
  })
}

export function useCrossAssetHeatmap() {
  return useQuery<CrossAssetHeatmap>({
    queryKey: ['dashboard', 'cross-asset-heatmap'],
    queryFn: () => get<CrossAssetHeatmap>('/dashboard/cross-asset-heatmap'),
    refetchInterval: 60_000,
  })
}

export function useResonanceHistory(days = 30) {
  return useQuery<ResonanceHistoryPoint[]>({
    queryKey: ['dashboard', 'resonance-history', days],
    queryFn: () => get<ResonanceHistoryPoint[]>(`/dashboard/resonance-history?days=${days}`),
    refetchInterval: 60_000,
  })
}
