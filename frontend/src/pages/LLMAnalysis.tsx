import { useState, useRef, useEffect, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Brain,
  AlertTriangle,
  Loader2,
  Clock,
  Coins,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Trash2,
  History,
  Sparkles,
} from 'lucide-react'
import { useLLMStatus, useLLMAnalyze } from '../api/llm'
import type { LLMAnalysisResult } from '../api/llm'
import { formatTime, formatRelativeTime } from '../utils/time'

// ── 资产选择器 (与后端 ASSET_OBFUSCATION_MAP 一致) ──
const SUPPORTED_ASSETS = [
  { symbol: 'SPX', label: 'S&P 500 指数' },
  { symbol: 'SPY', label: 'SPDR S&P 500 ETF' },
  { symbol: 'NDX', label: 'Nasdaq-100 指数' },
  { symbol: 'QQQ', label: 'Invesco QQQ' },
  { symbol: 'IWM', label: 'iShares Russell 2000' },
  { symbol: 'BTC', label: 'Bitcoin 现货' },
  { symbol: 'ETH', label: 'Ethereum 现货' },
]

// ── 历史记录 (localStorage 持久化, 不污染后端) ──
interface HistoryEntry {
  id: string
  asset: string
  timestamp: number
  result: LLMAnalysisResult
}

const HISTORY_KEY = 'llm-analysis-history-v2'
const HISTORY_MAX = 10

function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    return JSON.parse(raw)
  } catch {
    return []
  }
}

function saveHistory(entries: HistoryEntry[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries))
  } catch {
    /* quota or privacy mode — silently ignore */
  }
}

// ── 复制按钮 ──
function CopyButton({ text, label = '复制' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked — ignore */
    }
  }
  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-[var(--text-secondary)] hover:text-white hover:bg-white/5 transition-colors"
      title="复制到剪贴板"
    >
      {copied ? <Check size={12} className="text-[var(--accent-green)]" /> : <Copy size={12} />}
      {copied ? '已复制' : label}
    </button>
  )
}

// ── Markdown 组件 (自定义渲染, 适配深色主题) ──
function MarkdownBody({ content }: { content: string }) {
  return (
    <div
      className="
        prose prose-invert prose-sm max-w-none
        prose-headings:text-[var(--text-primary)] prose-headings:font-semibold
        prose-h1:text-base prose-h1:mt-5 prose-h1:mb-2
        prose-h2:text-sm prose-h2:text-[var(--accent-blue)] prose-h2:mt-4 prose-h2:mb-2 prose-h2:border-b prose-h2:border-[var(--border)] prose-h2:pb-1
        prose-h3:text-sm prose-h3:mt-3 prose-h3:mb-1
        prose-p:text-sm prose-p:text-[var(--text-primary)] prose-p:leading-relaxed prose-p:my-1.5
        prose-strong:text-[var(--text-primary)] prose-strong:font-semibold
        prose-em:text-[var(--text-secondary)] prose-em:italic
        prose-a:text-[var(--accent-blue)] prose-a:no-underline hover:prose-a:underline
        prose-code:bg-[var(--bg-primary)] prose-code:text-[var(--accent-yellow)] prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-[12px] prose-code:before:content-none prose-code:after:content-none
        prose-pre:bg-[var(--bg-primary)] prose-pre:border prose-pre:border-[var(--border)] prose-pre:rounded-lg prose-pre:p-3 prose-pre:my-2
        prose-blockquote:border-l-[3px] prose-blockquote:border-[var(--accent-yellow)] prose-blockquote:bg-[var(--accent-yellow)]/5 prose-blockquote:text-[var(--text-secondary)] prose-blockquote:px-3 prose-blockquote:py-1.5 prose-blockquote:rounded-r prose-blockquote:my-2
        prose-ul:my-1 prose-ol:my-1 prose-li:text-sm prose-li:text-[var(--text-primary)] prose-li:my-0.5
        prose-hr:border-[var(--border)] prose-hr:my-3
        prose-table:text-xs prose-th:text-[var(--text-secondary)] prose-td:text-[var(--text-primary)]
      "
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  )
}

// ── 可折叠节 ──
function CollapsibleSection({
  title,
  defaultOpen = true,
  icon,
  children,
  actions,
}: {
  title: string
  defaultOpen?: boolean
  icon?: ReactNode
  children: ReactNode
  actions?: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-white/5 transition-colors rounded-xl"
      >
        {open ? <ChevronDown size={14} className="text-[var(--text-secondary)]" /> : <ChevronRight size={14} className="text-[var(--text-secondary)]" />}
        {icon}
        <h3 className="text-sm font-semibold text-[var(--text-primary)] flex-1">{title}</h3>
        {actions && <div onClick={(e) => e.stopPropagation()}>{actions}</div>}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  )
}

// ── 结果卡片 ──
function ResultCard({ data }: { data: LLMAnalysisResult }) {
  const { briefing, tokens, latency_ms, report_markdown } = data
  const fullText = report_markdown || briefing.full_text

  return (
    <div className="space-y-3">
      {/* Hallucination Warning */}
      {briefing.has_hallucination && (
        <div className="flex items-start gap-2 bg-[var(--accent-yellow)]/10 border border-[var(--accent-yellow)]/30 rounded-xl p-3">
          <AlertTriangle size={18} className="text-[var(--accent-yellow)] shrink-0 mt-0.5" />
          <div className="text-xs text-[var(--text-primary)] flex-1">
            <strong className="text-[var(--accent-yellow)]">⚠️ 幻觉警告</strong> — LLM 输出包含与源数据不一致的内容
            <ul className="mt-1.5 space-y-0.5 list-disc list-inside">
              {briefing.hallucination_flags.map((f, i) => (
                <li key={i} className="text-[var(--text-secondary)]">{f}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Key Levels */}
      {briefing.key_levels && briefing.key_levels.length > 0 && (
        <CollapsibleSection title="📊 关键价位区" icon={<Sparkles size={14} className="text-[var(--accent-blue)]" />}>
          <div className="grid gap-2">
            {briefing.key_levels.map((kl, i) => (
              <div
                key={i}
                className="flex items-center justify-between bg-[var(--bg-primary)] rounded-lg px-3 py-2 hover:bg-white/5 transition-colors"
              >
                <div className="flex flex-col">
                  <span className="text-xs text-[var(--text-primary)] font-medium">{kl.label}</span>
                  <span className="text-[10px] text-[var(--text-secondary)]">{kl.significance}</span>
                </div>
                <span className="text-sm font-mono font-bold text-[var(--accent-blue)]">
                  {kl.level.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* Resonance Summary */}
      <CollapsibleSection title="📋 共振摘要" icon={<Brain size={14} className="text-[var(--accent-purple)]" />}>
        <MarkdownBody content={briefing.summary || '*LLM 未生成摘要*'} />
      </CollapsibleSection>

      {/* Full Markdown Report */}
      <CollapsibleSection
        title="📝 LLM 策略分析正文"
        icon={<Brain size={14} className="text-[var(--accent-blue)]" />}
        actions={<CopyButton text={fullText} />}
      >
        <div className="max-h-[600px] overflow-y-auto pr-1 -mr-1">
          <MarkdownBody content={fullText} />
        </div>
      </CollapsibleSection>

      {/* Scenarios / Positions / Hedging */}
      {(briefing.scenario || briefing.positions || briefing.hedging) && (
        <CollapsibleSection title="🎯 战术推演 (Scenario / Positions / Hedging)" defaultOpen={false}>
          <div className="space-y-3">
            {briefing.scenario && (
              <div>
                <div className="text-[10px] text-[var(--text-secondary)] mb-1 font-semibold uppercase tracking-wide">Scenario</div>
                <MarkdownBody content={briefing.scenario} />
              </div>
            )}
            {briefing.positions && (
              <div>
                <div className="text-[10px] text-[var(--text-secondary)] mb-1 font-semibold uppercase tracking-wide">Positions</div>
                <MarkdownBody content={briefing.positions} />
              </div>
            )}
            {briefing.hedging && (
              <div>
                <div className="text-[10px] text-[var(--text-secondary)] mb-1 font-semibold uppercase tracking-wide">Hedging</div>
                <MarkdownBody content={briefing.hedging} />
              </div>
            )}
          </div>
        </CollapsibleSection>
      )}

      {/* Risk Assessment */}
      {briefing.risk_assessment && (
        <CollapsibleSection title="⚡ 风险评估" defaultOpen={false}>
          <MarkdownBody content={briefing.risk_assessment} />
        </CollapsibleSection>
      )}

      {/* Token & Latency Footer */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--text-secondary)] bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-3">
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
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                briefing.conviction_level.includes('Extreme') || briefing.conviction_level === 'Strong'
                  ? 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]'
                  : briefing.conviction_level === 'Moderate'
                  ? 'bg-[var(--accent-yellow)]/15 text-[var(--accent-yellow)]'
                  : 'bg-[var(--text-secondary)]/15 text-[var(--text-secondary)]'
              }`}
            >
              {briefing.conviction_level}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── 历史对话侧栏 ──
function HistoryPanel({
  history,
  onSelect,
  onClear,
  currentId,
}: {
  history: HistoryEntry[]
  onSelect: (entry: HistoryEntry) => void
  onClear: () => void
  currentId?: string
}) {
  if (history.length === 0) {
    return (
      <div className="text-[10px] text-[var(--text-secondary)] italic px-1">
        暂无历史 (分析结果会自动保存到本地)
      </div>
    )
  }
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-[var(--text-secondary)] uppercase tracking-wide">
          最近 {history.length} 次
        </span>
        <button
          onClick={onClear}
          className="flex items-center gap-1 text-[10px] text-[var(--text-secondary)] hover:text-[var(--accent-red)] transition-colors"
        >
          <Trash2 size={10} />
          清空
        </button>
      </div>
      {history.map((h) => {
        const isCurrent = currentId === h.id
        const conviction = h.result.briefing.conviction_level
        return (
          <button
            key={h.id}
            onClick={() => onSelect(h)}
            className={`w-full text-left px-2 py-2 rounded-lg transition-colors ${
              isCurrent ? 'bg-[var(--accent-blue)]/15 border border-[var(--accent-blue)]/30' : 'hover:bg-white/5 border border-transparent'
            }`}
          >
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs font-medium text-[var(--text-primary)]">{h.asset}</span>
              <span className="text-[9px] text-[var(--text-secondary)]">
                {formatRelativeTime(new Date(h.timestamp).toISOString())}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)]">
              <span>{formatTime(new Date(h.timestamp).toISOString(), 'America/New_York', 'HH:mm')}</span>
              <span>·</span>
              <span>{h.result.tokens.toLocaleString()} tokens</span>
              {conviction && (
                <>
                  <span>·</span>
                  <span
                    className={
                      conviction.includes('Extreme') || conviction === 'Strong'
                        ? 'text-[var(--accent-green)]'
                        : conviction === 'Moderate'
                        ? 'text-[var(--accent-yellow)]'
                        : ''
                    }
                  >
                    {conviction}
                  </span>
                </>
              )}
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ── 主页面 ──
export default function LLMAnalysis() {
  const { data: status, isLoading: statusLoading } = useLLMStatus()
  const analyzeMutation = useLLMAnalyze()
  const [result, setResult] = useState<LLMAnalysisResult | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>(loadHistory)
  const [currentId, setCurrentId] = useState<string | undefined>()
  const [selectedAsset, setSelectedAsset] = useState<string>('SPX')
  const resultRef = useRef<HTMLDivElement>(null)

  // 持久化 history
  useEffect(() => {
    saveHistory(history)
  }, [history])

  // 新结果后自动滚动
  useEffect(() => {
    if (result && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [result])

  const handleAnalyze = () => {
    analyzeMutation.mutate(
      { asset: selectedAsset },
      {
        onSuccess: (data) => {
          setResult(data)
          const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
          const entry: HistoryEntry = {
            id,
            asset: selectedAsset,
            timestamp: Date.now(),
            result: data,
          }
          setHistory((prev) => [entry, ...prev].slice(0, HISTORY_MAX))
          setCurrentId(id)
        },
      },
    )
  }

  const handleSelectHistory = (entry: HistoryEntry) => {
    setResult(entry.result)
    setCurrentId(entry.id)
    setSelectedAsset(entry.asset)
  }

  const handleClearHistory = () => {
    setHistory([])
    setCurrentId(undefined)
  }

  const isConfigured = status?.configured ?? false
  const configMissing = !isConfigured && !statusLoading

  return (
    <div className="space-y-4 max-w-[1600px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">LLM 策略分析</h1>
          <p className="text-[10px] text-[var(--text-secondary)] mt-0.5">
            AI 多维度共振推理 · 做市商动力学 · 暗盘资金流 · 波动率景观 · <span className="text-[var(--accent-blue)]">V2.6 时间混淆</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Asset Selector */}
          <select
            value={selectedAsset}
            onChange={(e) => setSelectedAsset(e.target.value)}
            disabled={analyzeMutation.isPending}
            className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg px-2 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-blue)]/50 disabled:opacity-50"
          >
            {SUPPORTED_ASSETS.map((a) => (
              <option key={a.symbol} value={a.symbol}>
                {a.symbol} — {a.label}
              </option>
            ))}
          </select>
          {statusLoading ? (
            <span className="text-xs text-[var(--text-secondary)]">加载中...</span>
          ) : status ? (
            <div className="flex items-center gap-1.5 text-xs">
              <span className={`w-1.5 h-1.5 rounded-full ${isConfigured ? 'bg-[var(--accent-green)] animate-pulse' : 'bg-[var(--accent-red)]'}`} />
              <span className="text-[var(--text-secondary)]">{status.provider} · {status.model}</span>
            </div>
          ) : null}
        </div>
      </div>

      {/* Two-column layout: History | Content */}
      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-4">
        {/* Sidebar: History */}
        <aside className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-3 h-fit lg:sticky lg:top-4">
          <div className="flex items-center gap-2 mb-3 pb-2 border-b border-[var(--border)]">
            <History size={14} className="text-[var(--accent-blue)]" />
            <h2 className="text-xs font-semibold text-[var(--text-primary)]">分析历史</h2>
          </div>
          <HistoryPanel
            history={history}
            onSelect={handleSelectHistory}
            onClear={handleClearHistory}
            currentId={currentId}
          />
        </aside>

        {/* Main Content */}
        <div ref={resultRef} className="space-y-3 min-w-0">
          {/* Config Warning */}
          {configMissing && (
            <div className="flex items-start gap-2 bg-[var(--accent-yellow)]/10 border border-[var(--accent-yellow)]/30 rounded-xl p-3">
              <AlertTriangle size={16} className="text-[var(--accent-yellow)] shrink-0 mt-0.5" />
              <div className="text-xs text-[var(--text-primary)] flex-1">
                <strong className="text-[var(--accent-yellow)]">LLM 未配置</strong>
                <p className="text-[var(--text-secondary)] mt-0.5">
                  请在 <code className="bg-[var(--bg-primary)] px-1 rounded">.env</code> 中设置 OPENAI_API_KEY 和 OPENAI_BASE_URL
                </p>
              </div>
            </div>
          )}

          {/* Action Card */}
          {!result && (
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-8 flex flex-col items-center gap-4">
              <button
                onClick={handleAnalyze}
                disabled={analyzeMutation.isPending || !isConfigured}
                className="flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm transition-all
                  disabled:opacity-40 disabled:cursor-not-allowed
                  bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/90 text-white
                  shadow-lg shadow-[var(--accent-blue)]/25 hover:shadow-xl hover:shadow-[var(--accent-blue)]/40"
              >
                {analyzeMutation.isPending ? (
                  <>
                    <Loader2 size={20} className="animate-spin" />
                    正在调用 {selectedAsset} LLM 推理...
                  </>
                ) : (
                  <>
                    <Brain size={20} />
                    开始分析 {selectedAsset}
                  </>
                )}
              </button>
              <p className="text-xs text-[var(--text-secondary)] max-w-md text-center leading-relaxed">
                点击后将调用 LLM 分析 <strong className="text-[var(--text-primary)]">{selectedAsset}</strong> 当前共振数据,生成完整策略简报。
                V2.6 时间混淆已启用 — LLM 只会看到 <code className="bg-[var(--bg-primary)] px-1 rounded">Day 0</code> + 脱敏资产代号,无法对历史做后见之明偏差。
              </p>
            </div>
          )}

          {/* Loading State */}
          {analyzeMutation.isPending && (
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-8 flex flex-col items-center gap-3">
              <Loader2 size={32} className="animate-spin text-[var(--accent-blue)]" />
              <div className="text-sm text-[var(--text-primary)]">正在调用 LLM 推理引擎...</div>
              <div className="text-xs text-[var(--text-secondary)] max-w-sm text-center">
                请求正在通过 API 网关发送至 {status?.provider ?? 'LLM'} ({status?.model ?? '-'}),
                策略师正在分析 {selectedAsset} 六大维度的共振数据并生成策略简报
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
              <div className="flex-1">
                <h3 className="text-sm font-semibold text-[var(--accent-red)]">分析失败</h3>
                <p className="text-xs text-[var(--text-secondary)] mt-1">
                  {analyzeMutation.error?.message || '未知错误'}
                </p>
                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => handleAnalyze()}
                    className="text-xs text-[var(--accent-blue)] hover:underline"
                  >
                    重试
                  </button>
                  <button
                    onClick={() => { analyzeMutation.reset(); setResult(null); setCurrentId(undefined) }}
                    className="text-xs text-[var(--text-secondary)] hover:text-white"
                  >
                    清除
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Result */}
          {result && !analyzeMutation.isPending && <ResultCard data={result} />}
        </div>
      </div>
    </div>
  )
}