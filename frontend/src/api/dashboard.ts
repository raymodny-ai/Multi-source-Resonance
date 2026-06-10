import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { DashboardScores } from '../types/api'

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
