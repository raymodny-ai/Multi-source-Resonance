import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, post } from './client'
import type { AlertRecord, PaginatedResponse } from '../types/api'

export function useAlerts(page = 1, pageSize = 20, level?: string, acknowledged?: boolean) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (level && level !== 'ALL') params.set('level', level)
  if (acknowledged !== undefined) params.set('acknowledged', String(acknowledged))

  return useQuery<PaginatedResponse<AlertRecord>>({
    queryKey: ['alerts', page, pageSize, level, acknowledged],
    queryFn: () => get<PaginatedResponse<AlertRecord>>(`/alerts?${params.toString()}`),
  })
}

export function useAcknowledgeAlert() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => post(`/alerts/${id}/acknowledge`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}
