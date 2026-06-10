import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { SystemStatusData } from '../types/api'

export function useSystemStatus() {
  return useQuery<SystemStatusData>({
    queryKey: ['system', 'source-status'],
    queryFn: () => get<SystemStatusData>('/system/source-status'),
    refetchInterval: 15_000,
  })
}

/**
 * SSE 日志流连接 Hook - 返回 EventSource 控制
 */
export function createLogStream(
  onLine: (line: string, level: string) => void,
  onError?: () => void,
): EventSource {
  const es = new EventSource('/api/system/logs/stream')
  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onLine(data.line, data.level)
    } catch {
      onLine(event.data, 'INFO')
    }
  }
  es.onerror = () => {
    onError?.()
  }
  return es
}
