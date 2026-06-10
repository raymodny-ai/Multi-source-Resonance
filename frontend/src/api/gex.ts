import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { GEXHistoryPoint } from '../types/api'

export function useGEXHistory(days = 90) {
  return useQuery<GEXHistoryPoint[]>({
    queryKey: ['gex', 'history', days],
    queryFn: () => get<GEXHistoryPoint[]>(`/gex/history?days=${days}`),
    staleTime: 5 * 60 * 1000,
  })
}
