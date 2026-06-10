import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { SystemStatusData } from '../types/api'

export function useSystemStatus() {
  return useQuery<SystemStatusData>({
    queryKey: ['system', 'source-status'],
    queryFn: () => get<SystemStatusData>('/system/source-status'),
    refetchInterval: 15_000, // 15s 刷新
  })
}
