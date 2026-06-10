import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { Incident, IncidentDetail } from '../types/api'

export function useIncidents(days = 7) {
  return useQuery<{ incidents: Incident[] }>({
    queryKey: ['incidents', days],
    queryFn: () => get<{ incidents: Incident[] }>(`/incidents?days=${days}`),
    refetchInterval: 30_000,
  })
}

export function useIncidentDetail(id: number | null) {
  return useQuery<IncidentDetail>({
    queryKey: ['incident', id],
    queryFn: () => get<IncidentDetail>(`/incidents/${id}`),
    enabled: id != null,
  })
}
