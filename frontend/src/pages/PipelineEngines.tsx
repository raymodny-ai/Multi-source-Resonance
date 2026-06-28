import { useMemo, useState } from 'react'
import { Cpu, Database, Zap, Activity, CheckCircle2, AlertCircle, RefreshCw, Sparkles } from 'lucide-react'
import {
  usePipelineStats,
  usePipelineRecent,
  useClickHouseHealth,
  useClickHouseAggregate,
  useEngineInfo,
} from '../api/internal'

// ── 5 层管道定义 ──
const LAYER_DEFS = [
  { id: 'layer1_filter', label: 'L1 数据清洗', desc: 'OI/Spread/OI-Dollar 三重门控' },
  { id: 'layer2_gex', label: 'L2 GEX 计算', desc: 'P3 fast-vollib BS + P2 SVI 校准' },
  { id: 'layer3_resonance', label: 'L3 共振评分', desc: '5 维加权 (GEX/VIX/Crypto/Darkpool/Cross-Asset)' },
  { id: 'layer4_signal', label: 'L4 信号生成', desc: 'Hawkes 簇检测 + Alert Level 触发' },
  { id: 'layer5_llm', label: 'L5 LLM 推理', desc: 'V2.6 脱敏 prompt + Provider' },
]

// ── 卡片组件 ──
function EngineCard({
  title,
  icon: Icon,
  available,
  badge,
  children,
}: {
  title: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  available: boolean | null
  badge?: string
  children: React.ReactNode
}) {
  const statusColor =
    available === null
      ? 'var(--text-secondary)'
      : available
      ? 'var(--accent-green)'
      : 'var(--accent-red)'
  const StatusIcon = available === null ? RefreshCw : available ? CheckCircle2 : AlertCircle
  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon size={16} className="text-[var(--accent-blue)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
        </div>
        <div className="flex items-center gap-1.5">
          <StatusIcon size={12} className={available === null ? 'animate-spin' : ''} style={{ color: statusColor }} />
          {badge && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: `${statusColor}20`,
                color: statusColor,
              }}
            >
              {badge}
            </span>
          )}
        </div>
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function Stat({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="font-mono text-[var(--text-primary)]">
        {value}
        {unit && <span className="text-[var(--text-secondary)] ml-0.5">{unit}</span>}
      </span>
    </div>
  )
}

// ── P6 Pipeline Layer Bars ──
function PipelineLayerBars() {
  const { data, isLoading } = usePipelineStats(null, 50)
  const layers = data?.layers ?? []

  // 找全局 max 用于归一化
  const maxMs = useMemo(
    () => Math.max(1, ...layers.map((l) => l.stats.p99_ms || l.stats.max_ms || 0)),
    [layers],
  )

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-[var(--accent-blue)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">P6 管道监控 — 各层耗时 (p99)</h3>
        </div>
        <span className="text-[10px] text-[var(--text-secondary)]">最近 50 次</span>
      </div>

      {isLoading ? (
        <div className="h-32 rounded skeleton" />
      ) : layers.length === 0 ? (
        <div className="h-32 flex items-center justify-center text-xs text-[var(--text-secondary)]">
          {data?.error || '暂无指标数据 (pipeline 未运行)'}
        </div>
      ) : (
        <div className="space-y-3">
          {layers.map((entry) => {
            const def = LAYER_DEFS.find((d) => d.id === entry.layer)
            const { count, avg_ms, p95_ms, p99_ms } = entry.stats
            const pct = Math.min(100, (p99_ms / maxMs) * 100)
            const color =
              p99_ms > 500 ? 'var(--accent-red)' : p99_ms > 100 ? 'var(--accent-yellow)' : 'var(--accent-green)'
            return (
              <div key={entry.layer}>
                <div className="flex items-center justify-between mb-1">
                  <div>
                    <div className="text-xs font-medium text-[var(--text-primary)]">
                      {def?.label ?? entry.layer}
                    </div>
                    <div className="text-[10px] text-[var(--text-secondary)]">{def?.desc}</div>
                  </div>
                  <div className="text-right text-[10px] font-mono">
                    <div style={{ color }}>{p99_ms.toFixed(1)}ms</div>
                    <div className="text-[var(--text-secondary)]">{count}× runs</div>
                  </div>
                </div>
                <div className="relative h-2 bg-[var(--bg-primary)] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: color }}
                  />
                </div>
                <div className="flex justify-between text-[9px] text-[var(--text-secondary)] mt-0.5">
                  <span>avg {avg_ms.toFixed(1)}ms</span>
                  <span>p95 {p95_ms.toFixed(1)}ms</span>
                  <span>p99 {p99_ms.toFixed(1)}ms</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── P4 ClickHouse ──
function ClickHousePanel() {
  const { data: health, isLoading: hLoading } = useClickHouseHealth()
  const { data: agg, isLoading: aLoading } = useClickHouseAggregate(null, 30)

  const isDegraded = !health?.connected

  return (
    <EngineCard
      title="P4 ClickHouse 列式存储"
      icon={Database}
      available={health ? health.connected : null}
      badge={hLoading ? '查询中' : isDegraded ? '降级 (SQLite)' : 'ONLINE'}
    >
      <Stat label="后端" value={isDegraded ? 'SQLite (降级)' : 'ClickHouse'} />
      <Stat label="延迟" value={health?.latency_ms != null ? health.latency_ms.toFixed(1) : '-'} unit="ms" />
      <Stat label="总行数" value={health?.row_count ?? '-'} />
      <div className="pt-2 mt-2 border-t border-[var(--border)]">
        <div className="text-[10px] text-[var(--text-secondary)] mb-1">最近 30 天 GEX 聚合</div>
        {aLoading ? (
          <div className="h-6 rounded skeleton" />
        ) : agg && agg.rows.length > 0 ? (
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-[var(--text-primary)]">{agg.count} 行</span>
            <span className="text-[10px] text-[var(--accent-green)]">实时聚合查询 OK</span>
          </div>
        ) : (
          <div className="text-[10px] text-[var(--text-secondary)] italic">
            {agg?.reason || agg?.error || '暂无数据 (降级模式返回空)'}
          </div>
        )}
      </div>
    </EngineCard>
  )
}

// ── P3 Fast VolLib ──
function FastVolLibPanel() {
  const { data, isLoading } = useEngineInfo()
  const engine = data?.engines.fast_vollib
  return (
    <EngineCard
      title="P3 Fast VolLib"
      icon={Zap}
      available={engine ? engine.available : null}
      badge={isLoading ? '查询中' : engine?.available ? 'NUMPY' : 'STDLIB'}
    >
      <Stat label="后端" value={engine?.backend ?? '-'} />
      <Stat label="批量能力" value={engine?.batch_capacity ?? '-'} />
      {!engine?.available && engine?.error && (
        <div className="text-[10px] text-[var(--accent-red)] italic pt-1">{engine.error}</div>
      )}
    </EngineCard>
  )
}

// ── P2 SVI Calibrator ──
function SVIPanel() {
  const { data, isLoading } = useEngineInfo()
  const engine = data?.engines.svi
  return (
    <EngineCard
      title="P2 SVI 曲面校准"
      icon={Sparkles}
      available={engine ? engine.available : null}
      badge={isLoading ? '查询中' : engine?.available ? 'ACTIVE' : 'INACTIVE'}
    >
      <Stat label="校准器" value={engine?.calibrator ?? '-'} />
      <div className="text-[10px] text-[var(--text-secondary)]">参数</div>
      <div className="flex flex-wrap gap-1 mt-1">
        {(engine?.params ?? []).map((p) => (
          <span
            key={p}
            className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-[var(--accent-blue)]/10 text-[var(--accent-blue)]"
          >
            {p}
          </span>
        ))}
      </div>
    </EngineCard>
  )
}

// ── P5 VEX/CHEX ──
function VexChexPanel() {
  const { data, isLoading } = useEngineInfo()
  const engine = data?.engines.vex_chex
  return (
    <EngineCard
      title="P5 VEX / CHEX 张量"
      icon={Cpu}
      available={engine ? engine.available : null}
      badge={isLoading ? '查询中' : engine?.available ? 'OK' : 'ERR'}
    >
      <Stat label="计算器" value={(engine?.calculators ?? []).join(' · ') || '-'} />
      <div className="text-[10px] text-[var(--text-secondary)] mt-1 leading-relaxed">
        {engine?.metric ?? '-'}
      </div>
    </EngineCard>
  )
}

// ── P6 Recent Activity Feed ──
function PipelineRecentFeed() {
  const [layer, setLayer] = useState<string | undefined>(undefined)
  const { data, isLoading } = usePipelineRecent(layer, null, 20)
  const metrics = data?.metrics ?? []

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-[var(--accent-blue)]" />
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">P6 最近活动流</h3>
        </div>
        <select
          value={layer ?? ''}
          onChange={(e) => setLayer(e.target.value || undefined)}
          className="bg-[var(--bg-primary)] border border-[var(--border)] rounded px-2 py-1 text-[10px] text-[var(--text-primary)]"
        >
          <option value="">所有层</option>
          {LAYER_DEFS.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="h-32 rounded skeleton" />
      ) : metrics.length === 0 ? (
        <div className="h-32 flex items-center justify-center text-xs text-[var(--text-secondary)]">
          {data?.error || '暂无最近活动 (pipeline 未运行)'}
        </div>
      ) : (
        <div className="space-y-1 max-h-80 overflow-y-auto">
          {metrics.slice().reverse().map((m, idx) => {
            const def = LAYER_DEFS.find((d) => d.id === m.layer_name)
            const dur = m.duration_ms ?? 0
            const color =
              dur > 500 ? 'var(--accent-red)' : dur > 100 ? 'var(--accent-yellow)' : 'var(--accent-green)'
            const ts = m.timestamp ? new Date(m.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) : '-'
            return (
              <div
                key={`${m.layer_name}-${m.timestamp}-${idx}`}
                className="grid grid-cols-[80px_1fr_80px_70px] gap-2 text-[10px] py-1 px-2 rounded hover:bg-white/5 font-mono items-center"
              >
                <span className="text-[var(--text-secondary)]">{ts}</span>
                <span className="text-[var(--text-primary)] truncate">{def?.label ?? m.layer_name}</span>
                <span style={{ color }}>{dur.toFixed(1)}ms</span>
                <span className="text-[var(--text-secondary)] text-right">
                  {m.symbol ?? '-'} · {m.output_count ?? 0}/{m.input_count ?? 0}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Page ──
export default function PipelineEngines() {
  return (
    <div className="space-y-4 max-w-[1600px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">P1-P6 引擎总览</h1>
          <p className="text-[10px] text-[var(--text-secondary)] mt-0.5">
            V2.5 五大层级优化 — 流动性门控 / SVI 校准 / fast-vollib / ClickHouse / VEX-CHEX / 管道监控
          </p>
        </div>
      </div>

      {/* Row 1: Pipeline layer breakdown (full width) */}
      <PipelineLayerBars />

      {/* Row 2: 4 引擎卡片 (grid) */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <FastVolLibPanel />
        <SVIPanel />
        <ClickHousePanel />
        <VexChexPanel />
      </div>

      {/* Row 3: 最近活动流 */}
      <PipelineRecentFeed />

      {/* Footer note */}
      <p className="text-[10px] text-[var(--text-secondary)] text-right italic">
        数据源: <code className="font-mono">/api/internal/*</code> · 15s 自动刷新
      </p>
    </div>
  )
}