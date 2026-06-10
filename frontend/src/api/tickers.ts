import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { TickerInfo } from '../types/api'

export function useTickers() {
  return useQuery<TickerInfo[]>({
    queryKey: ['tickers'],
    queryFn: () => get<TickerInfo[]>('/tickers'),
    staleTime: 10 * 60 * 1000,
  })
}
