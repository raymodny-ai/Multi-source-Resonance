import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type {
  GEXSymbolStatus,
  GEXLatest,
  GEXMetrixHistoryPoint,
  GEXLevels,
  GEXSummary,
} from '../types/api'

// ── 标的列表 ──
export function useGEXSymbols() {
  return useQuery<GEXSymbolStatus[]>({
    queryKey: ['gexmetrix', 'symbols'],
    queryFn: () => get<GEXSymbolStatus[]>('/gex/symbols'),
    staleTime: 60 * 1000,
    refetchInterval: 5 * 60 * 1000, // 盘中每5分钟刷新
  })
}

// ── 全局摘要 ──
export function useGEXSummary() {
  return useQuery<GEXSummary>({
    queryKey: ['gexmetrix', 'summary'],
    queryFn: () => get<GEXSummary>('/gex/summary'),
    staleTime: 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  })
}

// ── 最新快照 ──
export function useGEXLatest(symbol: string | null) {
  return useQuery<GEXLatest>({
    queryKey: ['gexmetrix', 'latest', symbol],
    queryFn: () => get<GEXLatest>(`/gex/${symbol}/latest`),
    enabled: !!symbol,
    staleTime: 60 * 1000,
    refetchInterval: symbol ? 5 * 60 * 1000 : false,
  })
}

// ── 历史序列 ──
export function useGEXHistory(symbol: string | null, days = 7) {
  return useQuery<GEXMetrixHistoryPoint[]>({
    queryKey: ['gexmetrix', 'history', symbol, days],
    queryFn: () => get<GEXMetrixHistoryPoint[]>(`/gex/${symbol}/history?days=${days}`),
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
    staleTime: 60 * 1000,
    refetchInterval: symbol ? 5 * 60 * 1000 : false,
  })
}
