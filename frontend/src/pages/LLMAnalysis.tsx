import { useState, type ReactNode } from 'react'
import { Brain, AlertTriangle, Loader2, Clock, Coins } from 'lucide-react'
import { useLLMStatus, useLLMAnalyze } from '../api/llm'
import type { LLMAnalysisResult } from '../api/llm'

function MarkdownRenderer({ content }: { content: string }) {
  if (!content) return null

  // Split into blocks and render with basic Markdown support
  const lines = content.split('\n')
  const elements: ReactNode[] = []
  let inCodeBlock = false
  let codeContent: string[] = []
  let codeLang = ''

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    // Code block handling
    if (line.trim().startsWith('```')) {
      if (!inCodeBlock) {
        inCodeBlock = true
        codeLang = line.trim().slice(3)
        codeContent = []
        continue
      } else {
        inCodeBlock = false
        elements.push(
          <pre
            key={`code-${i}`}
            className="bg-[var(--bg-primary)] text-[var(--text-primary)] text-xs rounded-lg p-3 overflow-x-auto my-2 font-mono whitespace-pre"
          >
            <code>{codeContent.join('\n')}</code>
          </pre>
        )
        continue
      }
    }

    if (inCodeBlock) {
      codeContent.push(line)
      continue
    }

    // Blockquote
    if (line.trim().startsWith('>')) {
      elements.push(
        <blockquote
          key={`bq-${i}`}
          className="border-l-3 border-[var(--accent-yellow)] bg-[var(--accent-yellow)]/5 text-[var(--text-secondary)] text-sm px-3 py-1.5 rounded-r my-1"
        >
          {line.replace(/^>\s*/, '')}
        </blockquote>
      )
      continue
    }

    // Headers
    if (line.trim().startsWith('### ')) {
      elements.push(
        <h3 key={`h3-${i}`} className="text-sm font-semibold text-[var(--text-primary)] mt-4 mb-1">
          {line.replace(/^###\s*/, '')}
        </h3>
      )
      continue
    }
    if (line.trim().startsWith('## ')) {
      elements.push(
        <h3 key={`h2-${i}`} className="text-sm font-bold text-[var(--accent-blue)] mt-5 mb-2 border-b border-[var(--border)] pb-1">
          {line.replace(/^##\s*/, '')}
        </h3>
      )
      continue
    }
    if (line.trim().startsWith('# ')) {
      elements.push(
        <h2 key={`h1-${i}`} className="text-base font-bold text-[var(--text-primary)] mt-5 mb-2">
          {line.replace(/^#\s*/, '')}
        </h2>
      )
      continue
    }

    // Horizontal rule
    if (line.trim() === '---' || line.trim() === '***') {
      elements.push(<hr key={`hr-${i}`} className="border-[var(--border)] my-3" />)
      continue
    }

    // Bold and italic inline
    let processed = line
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code style="background:var(--bg-primary);padding:1px 4px;border-radius:3px;font-size:12px">$1</code>')

    // Bullet points
    const trimmed = line.trimStart()
    const indentLevel = line.length - trimmed.length
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ') || trimmed.match(/^\d+\.\s/)) {
      elements.push(
        <li key={`li-${i}`} className="text-sm text-[var(--text-primary)] ml-4 my-0.5 list-disc" style={{ marginLeft: `${indentLevel + 16}px` }}>
          <span dangerouslySetInnerHTML={{ __html: trimmed.replace(/^[-*\d]+\.\s*/, '') }} />
        </li>
      )
      continue
    }

    // Empty line
    if (trimmed === '') {
      elements.push(<div key={`sp-${i}`} className="h-2" />)
      continue
    }

    // Regular paragraph
    elements.push(
      <p key={`p-${i}`} className="text-sm text-[var(--text-primary)] my-1 leading-relaxed">
        <span dangerouslySetInnerHTML={{ __html: processed }} />
      </p>
    )
  }

  return <div className="space-y-0">{elements}</div>
}

function ResultCard({ data }: { data: LLMAnalysisResult }) {
  const { briefing, tokens, latency_ms, report_markdown } = data

  return (
    <div className="space-y-4">
      {/* Hallucination Warning */}
      {briefing.has_hallucination && (
        <div className="flex items-start gap-2 bg-[var(--accent-yellow)]/10 border border-[var(--accent-yellow)]/30 rounded-lg p-3">
          <AlertTriangle size={18} className="text-[var(--accent-yellow)] shrink-0 mt-0.5" />
          <div className="text-xs text-[var(--text-primary)]">
            <strong className="text-[var(--accent-yellow)]">⚠️ 幻觉警告</strong> — LLM 输出包含与源数据不一致的内容
            <ul className="mt-1 space-y-0.5">
              {briefing.hallucination_flags.map((f, i) => (
                <li key={i} className="text-[var(--text-secondary)]">{f}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Key Levels Summary */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">📊 关键价位区</h3>
        <div className="grid gap-2">
          {briefing.key_levels.map((kl, i) => (
            <div
              key={i}
              className="flex items-center justify-between bg-[var(--bg-primary)] rounded-lg px-3 py-2"
            >
              <div className="flex flex-col">
                <span className="text-xs text-[var(--text-secondary)]">{kl.label}</span>
                <span className="text-xs text-[var(--accent-blue)]">{kl.significance}</span>
              </div>
              <span className="text-sm font-mono font-bold text-[var(--text-primary)]">{kl.level.toFixed(0)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Resonance Summary */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">📋 共振摘要</h3>
        <div className="text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
          {briefing.summary || 'LLM 未生成摘要'}
        </div>
      </div>

      {/* Full Markdown Report */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">📝 LLM 策略分析正文</h3>
        <div className="max-h-[600px] overflow-y-auto pr-1">
          <MarkdownRenderer content={report_markdown || briefing.full_text} />
        </div>
      </div>

      {/* Token & Latency Footer */}
      <div className="flex items-center gap-4 text-xs text-[var(--text-secondary)]">
        <div className="flex items-center gap-1.5">
          <Coins size={14} />
          <span>Token 消耗: <strong className="text-[var(--text-primary)]">{tokens.toLocaleString()}</strong></span>
        </div>
        <div className="flex items-center gap-1.5">
          <Clock size={14} />
          <span>延迟: <strong className="text-[var(--text-primary)]">{latency_ms.toLocaleString()} ms</strong></span>
        </div>
        {briefing.conviction_level && (
          <div className="flex items-center gap-1.5 ml-auto">
            <span>置信度:</span>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
              briefing.conviction_level.includes('Extreme') || briefing.conviction_level === 'Strong'
                ? 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]'
                : briefing.conviction_level === 'Moderate'
                ? 'bg-[var(--accent-yellow)]/15 text-[var(--accent-yellow)]'
                : 'bg-[var(--text-secondary)]/15 text-[var(--text-secondary)]'
            }`}>
              {briefing.conviction_level}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function LLMAnalysis() {
  const { data: status, isLoading: statusLoading } = useLLMStatus()
  const analyzeMutation = useLLMAnalyze()
  const [result, setResult] = useState<LLMAnalysisResult | null>(null)

  const handleAnalyze = () => {
    analyzeMutation.mutate(
      { asset: 'SPX' },
      {
        onSuccess: (data) => {
          setResult(data)
        },
      }
    )
  }

  const isConfigured = status?.configured ?? false

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-[var(--text-primary)]">LLM 策略分析</h1>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            AI 多维度共振推理 · 做市商动力学 · 暗盘资金流 · 波动率景观
          </p>
        </div>
        <div className="flex items-center gap-2">
          {statusLoading ? (
            <span className="text-xs text-[var(--text-secondary)]">加载中...</span>
          ) : status ? (
            <div className="flex items-center gap-2">
              <span className={`w-1.5 h-1.5 rounded-full ${isConfigured ? 'bg-[var(--accent-green)]' : 'bg-[var(--accent-red)]'}`} />
              <span className="text-xs text-[var(--text-secondary)]">
                {status.model}
              </span>
            </div>
          ) : null}
        </div>
      </div>

      {/* Analyze Button */}
      {!result && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-8 flex flex-col items-center gap-4">
          {!isConfigured && !statusLoading && (
            <div className="flex items-start gap-2 bg-[var(--accent-yellow)]/10 border border-[var(--accent-yellow)]/30 rounded-lg p-3 mb-2 w-full max-w-md">
              <AlertTriangle size={16} className="text-[var(--accent-yellow)] shrink-0 mt-0.5" />
              <div className="text-xs text-[var(--text-primary)]">
                <strong className="text-[var(--accent-yellow)]">LLM 未配置</strong>
                <p className="text-[var(--text-secondary)] mt-0.5">
                  请在 <code className="bg-[var(--bg-primary)] px-1 rounded">.env</code> 中设置 OPENAI_API_KEY 和 OPENAI_BASE_URL
                </p>
              </div>
            </div>
          )}

          <button
            onClick={handleAnalyze}
            disabled={analyzeMutation.isPending || !isConfigured}
            className="flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm transition-all
              disabled:opacity-40 disabled:cursor-not-allowed
              bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/90 text-white
              shadow-lg shadow-[var(--accent-blue)]/25"
          >
            {analyzeMutation.isPending ? (
              <>
                <Loader2 size={20} className="animate-spin" />
                正在调用 LLM 推理引擎...
              </>
            ) : (
              <>
                <Brain size={20} />
                开始分析
              </>
            )}
          </button>

          <p className="text-xs text-[var(--text-secondary)] max-w-md text-center">
            点击后将调用 LLM 分析当前共振数据，生成完整的策略简报，包括关键价位区、做市商动力学、暗盘资金流向和次日战术建议
          </p>
        </div>
      )}

      {/* Loading State */}
      {analyzeMutation.isPending && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-8 flex flex-col items-center gap-3">
          <Loader2 size={32} className="animate-spin text-[var(--accent-blue)]" />
          <div className="text-sm text-[var(--text-primary)]">正在调用 LLM 推理引擎...</div>
          <div className="text-xs text-[var(--text-secondary)] max-w-sm text-center">
            请求正在通过 API 网关发送至 LLM 提供商，策略师正在分析六大维度的共振数据并生成策略简报
          </div>
          <div className="flex gap-1 mt-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="w-2 h-2 rounded-full bg-[var(--accent-blue)] animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
        </div>
      )}

      {/* Error State */}
      {analyzeMutation.isError && (
        <div className="bg-[var(--accent-red)]/10 border border-[var(--accent-red)]/30 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle size={20} className="text-[var(--accent-red)] shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-[var(--accent-red)]">分析失败</h3>
            <p className="text-xs text-[var(--text-secondary)] mt-1">
              {analyzeMutation.error?.message || '未知错误'}
            </p>
            <button
              onClick={() => { analyzeMutation.reset(); setResult(null) }}
              className="mt-2 text-xs text-[var(--accent-blue)] hover:underline"
            >
              重试
            </button>
          </div>
        </div>
      )}

      {/* Result */}
      {result && !analyzeMutation.isPending && (
        <ResultCard data={result} />
      )}
    </div>
  )
}
