import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, post } from './client'
import type { SignalRecord, PaginatedResponse } from '../types/api'

export function useCurrentSignal() {
  return useQuery({
    queryKey: ['signals', 'current'],
    queryFn: () => get('/signals/current'),
    refetchInterval: 30_000,
  })
}

export function useSignalHistory(days = 30, page = 1, pageSize = 50) {
  return useQuery<PaginatedResponse<SignalRecord>>({
    queryKey: ['signals', 'history', days, page, pageSize],
    queryFn: () =>
      get<PaginatedResponse<SignalRecord>>(
        `/signals/history?days=${days}&page=${page}&page_size=${pageSize}`,
      ),
  })
}

export function useAcknowledgeSignal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => post(`/signals/${id}/acknowledge`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['signals'] })
    },
  })
}
