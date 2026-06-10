import { useSystemStatus } from '../api/system'
import { useStalenessStore } from '../stores/stalenessStore'
import { formatRelativeTime } from '../utils/time'
import type { SourceStatus } from '../types/api'

function SourceCard({ source }: { source: SourceStatus }) {
  const getLastUpdated = useStalenessStore((s) => s.getLastUpdated)
  const lastUpdated = getLastUpdated(source.name)

  const statusConfig = {
    ONLINE: { color: 'bg-[var(--accent-green)]', border: 'border-[var(--accent-green)]/30', label: '🟢 正常' },
    DEGRADED: { color: 'bg-[var(--accent-yellow)]', border: 'border-[var(--accent-yellow)]/30', label: '🟡 降级' },
    OFFLINE: { color: 'bg-[var(--accent-red)]', border: 'border-[var(--accent-red)]/30', label: '🔴 故障' },
  }

  const config = statusConfig[source.status]

  return (
    <div className={`bg-[var(--bg-primary)] border ${config.border} rounded-lg p-3`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-[var(--text-primary)]">{source.name}</span>
        <span className={`w-2 h-2 rounded-full ${config.color}`} />
      </div>
      <p className="text-[10px] text-[var(--text-secondary)]">
        {config.label}
      </p>
      <p className="text-[10px] text-[var(--text-secondary)]">
        {source.availability_pct.toFixed(0)}% 可用
        {source.failure_count > 0 && ` · ${source.failure_count}次失败`}
      </p>
      {lastUpdated && (
        <p className="text-[10px] text-[var(--text-secondary)] mt-1">
          {formatRelativeTime(new Date(lastUpdated).toISOString())}
        </p>
      )}
    </div>
  )
}

export default function SystemStatus() {
  const { data, isLoading, isError } = useSystemStatus()

  return (
    <div className="space-y-4 max-w-[1600px]">
      <h1 className="text-xl font-bold">系统状态监控</h1>

      {/* Data source connectivity */}
      <section>
        <h2 className="text-sm font-semibold mb-3">数据源连通性</h2>
        {isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-20 rounded-lg skeleton" />
            ))}
          </div>
        ) : isError || !data ? (
          <div className="bg-[var(--bg-card)] border border-[var(--accent-red)]/30 rounded-xl p-4">
            <p className="text-xs text-[var(--accent-red)]">无法获取系统状态</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {data.sources.map((source) => (
              <SourceCard key={source.name} source={source} />
            ))}
          </div>
        )}
      </section>

      {/* Degradation mode + Scheduler */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-2">降级模式状态</h3>
          <span
            className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded ${
              data?.degradation_mode
                ? 'bg-[var(--accent-yellow)]/15 text-[var(--accent-yellow)]'
                : 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${data?.degradation_mode ? 'bg-[var(--accent-yellow)]' : 'bg-[var(--accent-green)]'}`}
            />
            {data?.degradation_mode ? '降级模式已激活' : '正常运行'}
          </span>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-2">调度器状态</h3>
          <span
            className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded ${
              data?.scheduler_running
                ? 'bg-[var(--accent-green)]/15 text-[var(--accent-green)]'
                : 'bg-[var(--accent-red)]/15 text-[var(--accent-red)]'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${data?.scheduler_running ? 'bg-[var(--accent-green)]' : 'bg-[var(--accent-red)]'}`}
            />
            {data?.scheduler_running ? '运行中' : '已停止'}
          </span>
        </div>
      </div>

      {/* Log stream placeholder */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
        <h3 className="text-sm font-semibold mb-3">实时日志流</h3>
        <div className="bg-[var(--bg-primary)] rounded-lg p-4 h-48 overflow-y-auto font-mono text-[11px] text-[var(--text-secondary)]">
          <p className="text-[var(--text-secondary)]">[系统日志] 连接日志流中...</p>
          <p className="text-[var(--text-secondary)] mt-1">点击展开查看实时任务调度与爬虫执行日志</p>
        </div>
      </div>
    </div>
  )
}
