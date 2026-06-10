import { useQuery, useMutation } from '@tanstack/react-query'
import { get, put } from './client'
import type { AppConfig } from '../types/api'

export function useConfig() {
  return useQuery<AppConfig>({
    queryKey: ['config'],
    queryFn: () => get<AppConfig>('/config'),
    staleTime: 10 * 60 * 1000,
  })
}

export function useUpdateConfig() {
  return useMutation({
    mutationFn: (config: Partial<AppConfig>) => put<AppConfig>('/config', config),
  })
}
