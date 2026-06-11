import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { get, post, put } from './client'
import type { SystemStatusData, ManualCollectResult, AutoPollingStatus } from '../types/api'

export function useSystemStatus() {
  return useQuery<SystemStatusData>({
    queryKey: ['system', 'source-status'],
    queryFn: () => get<SystemStatusData>('/system/source-status'),
    refetchInterval: 15_000,
  })
}

/**
 * 手动触发完整采集循环
 */
export function useTriggerManualCollect() {
  const queryClient = useQueryClient()
  return useMutation<ManualCollectResult, Error>({
    mutationFn: () => post<ManualCollectResult>('/system/collect-manual'),
    onSuccess: () => {
      // 刷新系统状态数据以反映最新连通性
      queryClient.invalidateQueries({ queryKey: ['system', 'source-status'] })
    },
  })
}

/**
 * 获取自动轮询开关状态
 */
export function useAutoPollingStatus() {
  return useQuery<AutoPollingStatus>({
    queryKey: ['system', 'auto-polling'],
    queryFn: () => get<AutoPollingStatus>('/system/auto-polling'),
    refetchInterval: 30_000,
  })
}

/**
 * 设置自动轮询开关
 */
export function useSetAutoPolling() {
  const queryClient = useQueryClient()
  return useMutation<AutoPollingStatus, Error, boolean>({
    mutationFn: (enabled: boolean) => put<AutoPollingStatus>('/system/auto-polling', { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system', 'auto-polling'] })
      queryClient.invalidateQueries({ queryKey: ['system', 'source-status'] })
    },
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
