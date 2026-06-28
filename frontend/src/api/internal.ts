import { useQuery } from '@tanstack/react-query'
import { get } from './client'

// ── P6 Pipeline Monitor ──
export interface PipelineLayerStats {
  count: number
  avg_ms: number
  min_ms: number
  max_ms: number
  p95_ms: number
  p99_ms: number
}

export interface PipelineLayerEntry {
  layer: string
  stats: PipelineLayerStats
}

export interface PipelineStatsResponse {
  layers: PipelineLayerEntry[]
  window: number
  error?: string
}

export interface PipelineMetricRecord {
  layer_name: string
  symbol: string | null
  timestamp: string
  duration_ms: number
  input_count: number
  output_count: number
  removed_count: number
  status: string
  metadata?: Record<string, unknown>
}

export interface PipelineRecentResponse {
  metrics: PipelineMetricRecord[]
  count: number
  error?: string
}

// ── P4 ClickHouse ──
export interface ClickHouseHealth {
  available: boolean
  connected: boolean
  degraded_mode: boolean
  latency_ms?: number
  row_count?: number
  error?: string
}

export interface ClickHouseAggregateRow {
  timestamp?: string
  symbol?: string
  net_gex?: number
  call_gex?: number
  put_gex?: number
  flip_point?: number
}

export interface ClickHouseAggregateResponse {
  rows: ClickHouseAggregateRow[]
  count: number
  degraded: boolean
  reason?: string
  error?: string
}

// ── P2/P3/P5 Engines ──
export interface EngineEntry {
  available: boolean
  backend?: string
  batch_capacity?: string
  calibrator?: string
  params?: string[]
  calculators?: string[]
  metric?: string
  error?: string
}

export interface EngineInfoResponse {
  timestamp: string
  engines: {
    fast_vollib?: EngineEntry
    svi?: EngineEntry
    vex_chex?: EngineEntry
  }
}

// ── Hooks ──

/** P6: 全部 5 层管道耗时聚合 */
export function usePipelineStats(symbol?: string | null, window = 50) {
  return useQuery<PipelineStatsResponse>({
    queryKey: ['internal', 'pipeline', 'stats', symbol, window],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('window', String(window))
      if (symbol) params.set('symbol', symbol)
      return get<PipelineStatsResponse>(`/internal/pipeline/stats?${params}`)
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  })
}

/** P6: 最近 N 条原始指标记录 */
export function usePipelineRecent(layer?: string, symbol?: string | null, limit = 50) {
  return useQuery<PipelineRecentResponse>({
    queryKey: ['internal', 'pipeline', 'recent', layer, symbol, limit],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('limit', String(limit))
      if (layer) params.set('layer', layer)
      if (symbol) params.set('symbol', symbol)
      return get<PipelineRecentResponse>(`/internal/pipeline/recent?${params}`)
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  })
}

/** P4: ClickHouse 连接健康 + 降级状态 */
export function useClickHouseHealth() {
  return useQuery<ClickHouseHealth>({
    queryKey: ['internal', 'clickhouse', 'health'],
    queryFn: () => get<ClickHouseHealth>('/internal/clickhouse/health'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

/** P4: ClickHouse GEX 聚合(降级时返回空 rows) */
export function useClickHouseAggregate(symbol?: string | null, days = 30) {
  return useQuery<ClickHouseAggregateResponse>({
    queryKey: ['internal', 'clickhouse', 'aggregate', symbol, days],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set('days', String(days))
      if (symbol) params.set('symbol', symbol)
      return get<ClickHouseAggregateResponse>(`/internal/clickhouse/aggregate?${params}`)
    },
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
}

/** P2/P3/P5: 三引擎可用性 + 配置摘要 */
export function useEngineInfo() {
  return useQuery<EngineInfoResponse>({
    queryKey: ['internal', 'engine', 'info'],
    queryFn: () => get<EngineInfoResponse>('/internal/engine/info'),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  })
}