import { useMutation, useQuery } from '@tanstack/react-query'
import { get, post } from './client'

export interface LLMAnalysisResult {
  report_markdown: string
  briefing: {
    full_text: string
    summary: string
    conviction_level: string
    risk_assessment: string
    key_levels: Array<{ level: number; label: string; significance: string }>
    scenario: string
    positions: string
    hedging: string
    has_hallucination: boolean
    hallucination_flags: string[]
  }
  tokens: number
  latency_ms: number
}

export interface LLMStatus {
  configured: boolean
  provider: string
  model: string
}

export function useLLMStatus() {
  return useQuery<LLMStatus>({
    queryKey: ['llm', 'status'],
    queryFn: () => get<LLMStatus>('/llm/status'),
    refetchInterval: 60_000,
  })
}

export function useLLMAnalyze() {
  return useMutation<LLMAnalysisResult, Error, { asset?: string }>({
    mutationFn: (params) => post<LLMAnalysisResult>('/llm/analyze', params),
  })
}
