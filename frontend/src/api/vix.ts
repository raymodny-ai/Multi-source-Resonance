import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { VIXHistoryPoint } from '../types/api'

export function useVIXHistory(days = 90) {
  return useQuery<VIXHistoryPoint[]>({
    queryKey: ['vix', 'history', days],
    queryFn: () => get<VIXHistoryPoint[]>(`/vix/history?days=${days}`),
    staleTime: 5 * 60 * 1000,
  })
}
