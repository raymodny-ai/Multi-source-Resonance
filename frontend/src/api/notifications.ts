import { useQuery, useMutation } from '@tanstack/react-query'
import { get, post, put } from './client'
import type { NotificationChannel, NotificationConfig } from '../types/api'

export function useNotificationStatus() {
  return useQuery<{ channels: NotificationChannel[] }>({
    queryKey: ['notifications', 'status'],
    queryFn: () => get<{ channels: NotificationChannel[] }>('/notifications/status'),
    refetchInterval: 60_000,
  })
}

export function useNotificationConfig() {
  return useQuery<NotificationConfig>({
    queryKey: ['notifications', 'config'],
    queryFn: () => get<NotificationConfig>('/notifications/config'),
    staleTime: 5 * 60 * 1000,
  })
}

export function useUpdateNotificationConfig() {
  return useMutation({
    mutationFn: (config: Partial<NotificationConfig>) => put('/notifications/config', config),
  })
}

export function useTestNotification() {
  return useMutation({
    mutationFn: (channel: string) => post('/notifications/test', { channel }),
  })
}
