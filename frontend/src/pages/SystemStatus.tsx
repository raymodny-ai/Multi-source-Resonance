import { useState, useEffect, useRef, useCallback } from 'react'
import { useSystemStatus, createLogStream, useTriggerManualCollect } from '../api/system'
import { formatRelativeTime } from '../utils/time'
import type { SourceStatus, ManualCollectResult } from '../types/api'
import { Pause, Play, Trash2, AlertTriangle, Download, CheckCircle, XCircle, Clock } from 'lucide-react'

function SourceCard({ source }: { source: SourceStatus }) {
  const statusConfig = {
    ONLINE: { color: 'bg-[var(--accent-green)]', border: 'border-[var(--accent-green)]/20', label: '🟢 正常', bg: 'bg-[var(--accent-green)]/5', icon: CheckCircle },
    DEGRADED: { color: 'bg-[var(--accent-yellow)]', border: 'border-[var(--accent-yellow)]/20', label: '🟡 待采集', bg: 'bg-[var(--accent-yellow)]/5', icon: Clock },
    OFFLINE: { color: 'bg-[var(--accent-red)]', border: 'border-[var(--accent-red)]/20', label: '🔴 失败', bg: 'bg-[var(--accent-red)]/5', icon: XCircle },
  }
  const config = statusConfig[source.status]
  const Icon = config.icon

  return (
    <div className={`${config.bg} border ${config.border} rounded-lg p-3 transition-all hover:border-white/10`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-[var(--text-primary)]">{source.name}</span>
        <span className={`w-2 h-2 rounded-full ${config.color} ${source.status === 'OFFLINE' ? 'animate-pulse' : ''}`} />
      </div>
      <div className="flex items-center gap-1 text-[10px] text-[var(--text-secondary)]">
        <Icon size={10} />
        <span>{config.label}</span>
      </div>
      <p className="text-[10px] text-[var(--text-secondary)] mt-1">
        {source.method}
        {source.last_elapsed_sec != null && <span className="ml-1 text-[var(--text-primary)]">· {source.last_elapsed_sec}s</span>}
      </p>
      {source.last_error && (
        <p className="text-[10px] text-[var(--accent-red)] mt-0.5 truncate" title={source.last_error}>
          {source.last_error}
        </p>
      )}
    </div>
  )
}

type LogEntry = { line: string; level: string; id: number }

export default function SystemStatus() {
  const { data, isLoading, isError } = useSystemStatus()
  const manualCollect = useTriggerManualCollect()
  const [logPaused, setLogPaused] = useState(false)
  const [errorOnly, setErrorOnly] = useState(false)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const logEndRef = useRef<HTMLDivElement>(null)
  const logIdRef = useRef(0)
  const esRef = useRef<EventSource | null>(null)

  // Toast notification state
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  // Manual collect result state (for persisting last results)
  const [lastResult, setLastResult] = useState<ManualCollectResult | null>(null)

  const handleManualCollect = useCallback(() => {
    manualCollect.mutate(undefined, {
      onSuccess: (result) => {
        setLastResult(result)
        setToast({
          type: result.success_count === result.total_sources ? 'success' : 'error',
          message: result.summary,
        })
      },
      onError: (err) => {
        setToast({ type: 'error', message: `手动采集失败: ${err.message}` })
      },
    })
  }, [manualCollect])

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 8000)
    return () => clearTimeout(timer)
  }, [toast])

  // SSE log stream
  useEffect(() => {
    const onLine = (line: string, level: string) => {
      logIdRef.current++
      setLogs((prev) => {
        const next = [...prev, { line, level, id: logIdRef.current }]
        return next.length > 200 ? next.slice(-200) : next
      })
    }
    esRef.current = createLogStream(onLine)
    return () => {
      esRef.current?.close()
    }
  }, [])

  // Auto-scroll
  useEffect(() => {
    if (!logPaused) {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, logPaused])

  const clearLogs = useCallback(() => setLogs([]), [])

  const filteredLogs = errorOnly ? logs.filter((l) => l.level === 'ERROR') : logs

  return (
    <div className="space-y-4 max-w-[1600px]">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">系统状态监控</h1>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--accent-yellow)]/20 text-[var(--accent-yellow)] font-mono">
          手动采集模式
        </span>
      </div>

      {/* Manual-only mode banner */}
      <div className="bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/30 rounded-xl p-3 flex items-center gap-2">
        <Clock size={16} className="text-[var(--accent-blue)] shrink-0" />
        <span className="text-xs text-[var(--accent-blue)] font-medium">
          系统运行在手动采集模式 — 点击下方按钮触发数据拉取 (6 数据源: GEX/DIX · VIX期限 · AXLFI暗盘 · DBMF · 加密衍生品 · 做空数据)
        </span>
      </div>

      {/* Toast notification */}
      {toast && (
        <div className={`rounded-xl p-3 flex items-center gap-2 transition-all animate-in slide-in-from-top-2 ${
          toast.type === 'success' ? 'bg-[var(--accent-green)]/10 border border-[var(--accent-green)]/30' : 'bg-[var(--accent-red)]/10 border border-[var(--accent-red)]/30'
        }`}>
          <span className={`w-2 h-2 rounded-full ${toast.type === 'success' ? 'bg-[var(--accent-green)]' : 'bg-[var(--accent-red)]'}`} />
          <span className={`text-xs ${toast.type === 'success' ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>{toast.message}</span>
          <button onClick={() => setToast(null)} className="ml-auto text-[var(--text-secondary)] hover:text-white text-xs">✕</button>
        </div>
      )}

      {/* Data source connectivity matrix */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold">数据源连通性矩阵</h2>
          <button
            onClick={handleManualCollect}
            disabled={manualCollect.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] rounded-lg font-medium bg-[var(--accent-blue)] text-white hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            title="手动采集全部 6 数据源"
          >
            <Download size={13} className={manualCollect.isPending ? 'animate-spin' : ''} />
            {manualCollect.isPending ? '采集中...' : '手动采集全部数据'}
          </button>
        </div>

        {/* Manual collect progress */}
        {manualCollect.isPending && (
          <div className="mb-3 flex items-center gap-2 bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 rounded-lg px-3 py-2">
            <Download size={12} className="text-[var(--accent-blue)] animate-spin" />
            <span className="text-[11px] text-[var(--accent-blue)]">
              正在采集: GEX/DIX · VIX期限结构 · AXLFI暗盘 · DBMF均线 · 加密衍生品 · 做空数据...
            </span>
          </div>
        )}

        {isLoading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-24 rounded-lg skeleton" />
            ))}
          </div>
        ) : isError || !data ? (
          <div className="bg-[var(--bg-card)] border border-[var(--accent-red)]/30 rounded-xl p-4">
            <p className="text-xs text-[var(--accent-red)]">无法获取系统状态</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
              {data.sources.map((source) => (
                <SourceCard key={source.name} source={source} />
              ))}
            </div>
            {/* Last manual collect summary */}
            {data.last_manual_collect && (
              <p className="text-[10px] text-[var(--text-secondary)] mt-2">
                上次采集: {formatRelativeTime(data.last_manual_collect)}
                {data.last_collect_summary && <span className="ml-2">— {data.last_collect_summary}</span>}
              </p>
            )}
          </>
        )}
      </section>

      {/* Detailed Collect Results */}
      {lastResult && (
        <section className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">
            最近采集详情
            <span className="ml-2 text-[10px] font-normal text-[var(--text-secondary)]">
              {lastResult.collected_at ? formatRelativeTime(lastResult.collected_at) : ''}
            </span>
          </h3>
          <div className="space-y-1.5">
            {lastResult.sources.map((src) => (
              <div key={src.name} className="flex items-center gap-3 text-[11px] py-1.5 px-3 rounded-lg bg-[var(--bg-primary)]">
                <span className={`shrink-0 ${src.status === 'success' ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>
                  {src.status === 'success' ? <CheckCircle size={13} /> : <XCircle size={13} />}
                </span>
                <span className="w-24 font-medium text-[var(--text-primary)]">{src.name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                  src.status === 'success' ? 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]' : 'bg-[var(--accent-red)]/15 text-[var(--accent-red)]'
                }`}>
                  {src.status === 'success' ? '成功' : '失败'}
                </span>
                <span className="text-[var(--text-secondary)]">{src.elapsed_sec}s</span>
                {src.error && <span className="text-[var(--accent-red)] truncate flex-1" title={src.error}>{src.error}</span>}
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className={`px-2 py-0.5 rounded font-medium ${
              lastResult.success_count === lastResult.total_sources ? 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]' : 'bg-[var(--accent-yellow)]/15 text-[var(--accent-yellow)]'
            }`}>
              {lastResult.success_count}/{lastResult.total_sources} 成功
            </span>
            <span className="text-[var(--text-secondary)]">总耗时 {lastResult.total_elapsed_sec}s</span>
          </div>
        </section>
      )}

      {/* Scheduler + DB */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">系统状态</h3>
          <div className="space-y-2 text-[10px]">
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-secondary)]">调度器</span>
              <span className="flex items-center gap-1 text-[var(--accent-yellow)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-yellow)]" />
                手动模式 (无自动任务)
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-secondary)]">数据库</span>
              <span className="text-[var(--text-primary)]">{data?.db_size_mb?.toFixed(1) ?? '--'} MB</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-secondary)]">上次备份</span>
              <span className="text-[var(--text-primary)]">{data?.last_backup_time ? formatRelativeTime(data.last_backup_time) : '--'}</span>
            </div>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">采集统计</h3>
          <div className="space-y-2 text-[10px]">
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-secondary)]">上次采集</span>
              <span className="text-[var(--text-primary)]">
                {data?.last_manual_collect ? formatRelativeTime(data.last_manual_collect) : '尚未采集'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-secondary)]">采集模式</span>
              <span className="text-[var(--accent-blue)]">纯手动触发</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-secondary)]">自动轮询</span>
              <span className="text-[var(--accent-red)]">已永久禁用</span>
            </div>
          </div>
        </div>
      </div>

      {/* Real-time log stream */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold">实时任务日志流</h3>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setErrorOnly(!errorOnly)}
              className={`px-2 py-1 text-[10px] rounded-md transition-colors ${errorOnly ? 'bg-[var(--accent-red)]/15 text-[var(--accent-red)]' : 'text-[var(--text-secondary)] hover:text-white'}`}
            >
              仅错误
            </button>
            <button
              onClick={() => setLogPaused(!logPaused)}
              className="p-1 rounded-md text-[var(--text-secondary)] hover:text-white transition-colors"
              title={logPaused ? '恢复滚动' : '暂停滚动'}
            >
              {logPaused ? <Play size={14} /> : <Pause size={14} />}
            </button>
            <button
              onClick={clearLogs}
              className="p-1 rounded-md text-[var(--text-secondary)] hover:text-white transition-colors"
              title="清空日志"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
        <div className="bg-[var(--bg-primary)] rounded-lg p-3 h-56 overflow-y-auto font-mono text-[11px] leading-relaxed">
          {filteredLogs.length === 0 ? (
            <p className="text-[var(--text-secondary)]">等待日志数据...</p>
          ) : (
            filteredLogs.map((log) => (
              <p
                key={log.id}
                className={
                  log.level === 'ERROR' ? 'text-[var(--accent-red)]' :
                  log.level === 'WARN' ? 'text-[var(--accent-yellow)]' :
                  log.level === 'SUCCESS' ? 'text-[var(--accent-green)]' :
                  'text-[var(--text-secondary)]'
                }
              >
                {log.line}
              </p>
            ))
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  )
}
