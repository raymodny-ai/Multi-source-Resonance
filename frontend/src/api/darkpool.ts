import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { DarkpoolHistoryPoint } from '../types/api'

export function useDarkpoolHistory(days = 90) {
  return useQuery<DarkpoolHistoryPoint[]>({
    queryKey: ['darkpool', 'history', days],
    queryFn: () => get<DarkpoolHistoryPoint[]>(`/darkpool/history?days=${days}`),
    staleTime: 5 * 60 * 1000,
  })
}
