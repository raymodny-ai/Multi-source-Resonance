import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, put, post } from './client'
import type { AppConfig, ConfigAuditEntry } from '../types/api'

export function useConfig() {
  return useQuery<AppConfig>({
    queryKey: ['config'],
    queryFn: () => get<AppConfig>('/config'),
    staleTime: 10 * 60 * 1000,
  })
}

export function useUpdateConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (config: Partial<AppConfig>) => put<AppConfig>('/config', config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
  })
}

export function useConfigDefaults() {
  return useQuery<AppConfig>({
    queryKey: ['config', 'defaults'],
    queryFn: () => get<AppConfig>('/config/defaults'),
    staleTime: 30 * 60 * 1000,
  })
}

export function useConfigAudit() {
  return useQuery<{ audit_logs: ConfigAuditEntry[] }>({
    queryKey: ['config', 'audit'],
    queryFn: () => get<{ audit_logs: ConfigAuditEntry[] }>('/config/audit'),
  })
}

export function useRestoreConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (version: string) => post(`/config/restore?version=${version}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
  })
}
