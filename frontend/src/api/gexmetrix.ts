import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type {
  GEXSymbolStatus,
  GEXLatest,
  GEXMetrixHistoryPoint,
  GEXLevels,
  GEXSummary,
} from '../types/api'

// B: 真实逐 strike 数据
export interface GEXStrike {
  strike: number
  call_gex: number
  put_gex: number
  call_oi: number
  put_oi: number
  call_vol: number
  put_vol: number
  net_gex: number
}
export interface GEXStrikesResponse {
  symbol: string
  timestamp: string
  spot_price: number | null
  strikes: GEXStrike[]
  strike_count: number
}

// C: BFF 聚合接口响应
export interface GEXDashboardView {
  symbol: string
  fetched_at: string
  latest: any | null  // gex_snapshots row
  levels: {
    call_wall: number | null
    put_wall: number | null
    zero_gamma_level: number | null
    spot_price: number | null
    net_gex: number | null
    call_gex: number | null
    put_gex: number | null
  } | null
  history: any[]  // gex_snapshots 时间序列
  long_history: any[]  // gex_history SqueezeMetrics 90 天
  strikes: GEXStrikesResponse  // 真实 strikes
  symbols: any[]  // 标的列表 + 新鲜度
}

// ── 标的列表 ──
export function useGEXSymbols() {
  return useQuery<GEXSymbolStatus[]>({
    queryKey: ['gexmetrix', 'symbols'],
    queryFn: () => get<GEXSymbolStatus[]>('/gex/symbols'),
    staleTime: 5 * 60 * 1000,  // 三.1: 与 refetchInterval 5min 对齐, 避免窗口聚焦时多余请求
    refetchInterval: 5 * 60 * 1000, // 盘中每5分钟刷新
  })
}

// ── 全局摘要 ──
export function useGEXSummary() {
  return useQuery<GEXSummary>({
    queryKey: ['gexmetrix', 'summary'],
    queryFn: () => get<GEXSummary>('/gex/summary'),
    staleTime: 5 * 60 * 1000,  // 三.1: 与 refetchInterval 5min 对齐, 避免窗口聚焦时多余请求
    refetchInterval: 5 * 60 * 1000,
  })
}

// ── 最新快照 ──
export function useGEXLatest(symbol: string | null) {
  return useQuery<GEXLatest>({
    queryKey: ['gexmetrix', 'latest', symbol],
    queryFn: () => get<GEXLatest>(`/gex/${symbol}/latest`),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,  // 三.1: 与 refetchInterval 5min 对齐, 避免窗口聚焦时多余请求
    refetchInterval: symbol ? 5 * 60 * 1000 : false,
  })
}

// ── 历史序列 ──
// 一.1: 智能切源 - 短期 GEXMetrix (6 标的), 中长期 SqueezeMetrics (仅 SPX, 90 天)
// 这是 gex_history 表只有 SPX 一档 (SqueezeMetrics 指数级), 非 SPX 不能用中长期窗口
export function useGEXHistory(symbol: string | null, days = 7) {
  return useQuery<GEXMetrixHistoryPoint[]>({
    queryKey: ['gexmetrix', 'history', symbol, days],
    queryFn: () => {
      if (days <= 3) {
        // GEXMetrix 真数据 (gex_snapshots, 6 标的都有)
        return get<GEXMetrixHistoryPoint[]>(`/gex/${symbol}/history?days=${days}`)
      }
      // 中长期 → SqueezeMetrics 90 天 (仅 SPX 有意义, 前端会保证只有 SPX 走这条)
      return get<GEXMetrixHistoryPoint[]>(`/gex/history?days=${days}`)
    },
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
  })
}

// ── 关键价位 ──
export function useGEXLevels(symbol: string | null) {
  return useQuery<GEXLevels>({
    queryKey: ['gexmetrix', 'levels', symbol],
    queryFn: () => get<GEXLevels>(`/gex/${symbol}/levels`),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,  // 三.1: 与 refetchInterval 5min 对齐, 避免窗口聚焦时多余请求
    refetchInterval: symbol ? 5 * 60 * 1000 : false,
  })
}

// ── 逐 strike 真实分布 (B) ──
export function useGEXStrikes(symbol: string | null, limit: number = 200) {
  return useQuery<GEXStrikesResponse>({
    queryKey: ['gexmetrix', 'strikes', symbol, limit],
    queryFn: () => get<GEXStrikesResponse>(`/gex/${symbol}/strikes?limit=${limit}`),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,  // 三.1: 与 refetchInterval 5min 对齐
    refetchInterval: symbol ? 5 * 60 * 1000 : false,
  })
}

// ── C: BFF 聚合接口 ──
// 一次返回 latest/levels/history/long_history/strikes/symbols, 替代 6 个独立 useQuery
export function useGEXDashboardView(
  symbol: string | null,
  options?: { history_days?: number; long_days?: number; strikes_limit?: number }
) {
  const params = new URLSearchParams()
  params.set('history_days', String(options?.history_days ?? 3))
  params.set('long_days', String(options?.long_days ?? 90))
  params.set('strikes_limit', String(options?.strikes_limit ?? 200))
  return useQuery<GEXDashboardView>({
    queryKey: ['gexmetrix', 'dashboard-view', symbol, params.toString()],
    queryFn: () => get<GEXDashboardView>(`/gex/${symbol}/dashboard-view?${params}`),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    refetchInterval: symbol ? 5 * 60 * 1000 : false,
  })
}
