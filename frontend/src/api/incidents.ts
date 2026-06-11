import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, put } from './client'
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

export function useReviewIncident() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => put(`/incidents/${id}/review`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incidents'] })
    },
  })
}

export function useExportIncident() {
  return useMutation({
    mutationFn: async (incident: IncidentDetail) => {
      const exportData = await get<Record<string, unknown>>(`/incidents/${incident.id}/export`)
      // Download as JSON
      const json = JSON.stringify(exportData, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `incident-${incident.id}-report.json`
      a.click()
      URL.revokeObjectURL(url)
    },
  })
}
