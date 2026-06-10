import { useState, useEffect, useRef, useCallback } from 'react'
import { useSystemStatus, createLogStream } from '../api/system'
import { formatRelativeTime } from '../utils/time'
import type { SourceStatus } from '../types/api'
import { Pause, Play, Trash2, AlertTriangle } from 'lucide-react'

function SourceCard({ source }: { source: SourceStatus }) {
  const statusConfig = {
    ONLINE: { color: 'bg-[var(--accent-green)]', border: 'border-[var(--accent-green)]/20', label: '🟢 正常', bg: 'bg-[var(--accent-green)]/5' },
    DEGRADED: { color: 'bg-[var(--accent-yellow)]', border: 'border-[var(--accent-yellow)]/20', label: '🟡 降级', bg: 'bg-[var(--accent-yellow)]/5' },
    OFFLINE: { color: 'bg-[var(--accent-red)]', border: 'border-[var(--accent-red)]/20', label: '🔴 故障', bg: 'bg-[var(--accent-red)]/5' },
  }
  const config = statusConfig[source.status]

  return (
    <div className={`${config.bg} border ${config.border} rounded-lg p-3 transition-all hover:border-white/10`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-[var(--text-primary)]">{source.name}</span>
        <span className={`w-2 h-2 rounded-full ${config.color} ${source.status === 'OFFLINE' ? 'animate-pulse' : ''}`} />
      </div>
      <p className="text-[10px] text-[var(--text-secondary)]">{config.label}</p>
      <p className="text-[10px] text-[var(--text-secondary)] mt-1">
        {source.method} · {source.availability_pct.toFixed(0)}% 可用
        {source.failure_count > 0 && <span className="text-[var(--accent-red)]"> · {source.failure_count}次失败</span>}
      </p>
    </div>
  )
}

type LogEntry = { line: string; level: string; id: number }

export default function SystemStatus() {
  const { data, isLoading, isError } = useSystemStatus()
  const [logPaused, setLogPaused] = useState(false)
  const [errorOnly, setErrorOnly] = useState(false)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const logEndRef = useRef<HTMLDivElement>(null)
  const logIdRef = useRef(0)
  const esRef = useRef<EventSource | null>(null)

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
      <h1 className="text-xl font-bold">系统状态监控</h1>

      {/* Data source connectivity matrix */}
      <section>
        <h2 className="text-sm font-semibold mb-3">爬虫连通性矩阵</h2>
        {isLoading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {[1, 2, 3, 4, 5, 6, 7].map((i) => (
              <div key={i} className="h-24 rounded-lg skeleton" />
            ))}
          </div>
        ) : isError || !data ? (
          <div className="bg-[var(--bg-card)] border border-[var(--accent-red)]/30 rounded-xl p-4">
            <p className="text-xs text-[var(--accent-red)]">无法获取系统状态</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {data.sources.map((source) => (
              <SourceCard key={source.name} source={source} />
            ))}
          </div>
        )}
      </section>

      {/* Degradation + Circuit Breaker + Scheduler */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Degradation mode */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">降级模式</h3>
          <div className={`inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg ${
            data?.degradation_mode ? 'bg-[var(--accent-yellow)]/15 text-[var(--accent-yellow)]' : 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]'
          }`}>
            <span className={`w-2 h-2 rounded-full ${data?.degradation_mode ? 'bg-[var(--accent-yellow)]' : 'bg-[var(--accent-green)]'}`} />
            {data?.degradation_mode ? 'PARTIAL 降级' : 'FULL 全功能'}
          </div>
          {data?.degradation_mode && data.degradation_details.failed_sources.length > 0 && (
            <p className="text-[10px] text-[var(--accent-yellow)] mt-2">
              <AlertTriangle size={10} className="inline mr-1" />
              失败源: {data.degradation_details.failed_sources.join(', ')}
            </p>
          )}
        </div>

        {/* Circuit breaker states */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">熔断器状态</h3>
          <div className="space-y-1.5">
            {data?.degradation_details.circuit_breaker_states ? (
              Object.entries(data.degradation_details.circuit_breaker_states).map(([source, state]) => (
                <div key={source} className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--text-secondary)]">{source}</span>
                  <span className={`px-1.5 py-0.5 rounded font-medium ${
                    state === 'CLOSED' ? 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]' :
                    state === 'OPEN' ? 'bg-[var(--accent-red)]/15 text-[var(--accent-red)]' :
                    'bg-[var(--accent-yellow)]/15 text-[var(--accent-yellow)]'
                  }`}>{state}</span>
                </div>
              ))
            ) : (
              <p className="text-[10px] text-[var(--text-secondary)]">加载中...</p>
            )}
          </div>
        </div>

        {/* Scheduler + DB */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3">调度器 & 数据库</h3>
          <div className="space-y-2 text-[10px]">
            <div className="flex items-center justify-between">
              <span className="text-[var(--text-secondary)]">调度器</span>
              <span className={`flex items-center gap-1 ${data?.scheduler_running ? 'text-[var(--accent-green)]' : 'text-[var(--accent-red)]'}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${data?.scheduler_running ? 'bg-[var(--accent-green)]' : 'bg-[var(--accent-red)]'}`} />
                {data?.scheduler_running ? '运行中' : '已停止'}
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
                className={log.level === 'ERROR' ? 'text-[var(--accent-red)]' : 'text-[var(--text-secondary)]'}
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
