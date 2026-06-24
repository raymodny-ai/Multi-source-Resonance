// ============ API 响应类型定义 ============

// --- 共振信号 ---
export type AlertLevel = 'LEVEL_1' | 'LEVEL_2' | 'LEVEL_3' | 'NO_SIGNAL'

export interface ResonanceResult {
  total_score: number
  max_score: number
  alert_level: AlertLevel
  resonance_pct: number
}

export interface HawkesResult {
  branching_ratio: number
  state: 'SUBCRITICAL' | 'CRITICAL' | 'SUPERCRITICAL'
  details: string
}

// --- 各维度数据 ---
export interface GEXData {
  score: number
  state: string
  details: string
  gex_local: number
  gex_calibrated: number
  put_wall_level: number
  flip_zone_lower: number
  flip_zone_upper: number
}

export interface VIXData {
  score: number
  state: string
  details: string
  vix_spot: number
  vx1: number
  vx2: number
  term_structure_ratio: number
  panic_premium: number
}

export interface CryptoData {
  score: number
  state: string
  details: string
  btc_funding_rate: number
  btc_oi: number
  oi_change_1h: number
  oi_crash: boolean
  funding_anomaly: boolean
  leverage_cleanup_confirmed: boolean
}

export interface DarkpoolData {
  score: number
  state: string
  details: string
  dix_value: number
  dix_signal: boolean
  short_ratio: number
  short_ratio_signal: boolean
  slope_20d: number
  slope_60d: number
  stockgrid_divergence: boolean
  stockgrid_signal: boolean
  dbmf_ma5_recovery: boolean
  available_sources: {
    dix: boolean
    short_ratio: boolean
    stockgrid: boolean
  }
  
  
  v_net: number
  ema_fast_5: number
  ema_slow_20: number
  zero_cross_signal: string | null
  momentum_reversal_signal: string | null
}

// --- 仪表盘总响应 ---
export interface DashboardScores {
  timestamp: string
  resonance: ResonanceResult
  dimensions: {
    gex: GEXData
    vix: VIXData
    crypto: CryptoData
    darkpool: DarkpoolData
    cross_asset: CrossAssetData
  }
  hawkes: HawkesResult
}

// --- 跨资产共振 ---
export interface CrossAssetData {
  score: number
  state: string
  details: string
  coherence_score: number
  alignment_direction: string
  resonance_strength: string
  alignment_count: number
}

// --- 跨资产热力图 ---
export interface CrossAssetHeatmap {
  assets: string[]
  signals: number[]
  matrix: number[][]
  overall_coherence: number
}

// --- 共振历史趋势 ---
export interface ResonanceHistoryPoint {
  timestamp: string
  total_score: number
  alert_level: string
}

// --- GEX 曲线 ---
export interface GEXCurve {
  timestamps: string[]
  gex_calibrated: number[]
  put_wall_level: number[]
  flip_zone_lower: number[]
  flip_zone_upper: number[]
}

// --- GEXMetrix Gamma Dashboard ---
export interface GEXSymbolStatus {
  symbol: string
  latest_timestamp: string
  snapshot_count: number
  age_minutes: number | null
}

export interface GEXLatest {
  symbol: string
  timestamp: string
  net_gex: number | null
  call_gex: number | null
  put_gex: number | null
  zero_gamma_level: number | null
  call_wall: number | null
  put_wall: number | null
  spot_price: number | null
  total_gamma: number | null
  file_size: number | null
}

export interface GEXMetrixHistoryPoint {
  timestamp: string
  net_gex: number | null
  spot_price: number | null
}

export interface GEXLevels {
  symbol: string
  timestamp: string
  zero_gamma_level: number | null
  call_wall: number | null
  put_wall: number | null
  spot_price: number | null
  net_gex: number | null
}

export interface GEXSummary {
  total_symbols: number
  latest_update: string | null
  total_snapshots: number
  symbols: GEXSymbolStatus[]
}

// --- 历史序列数据 ---
export interface HistoryDataPoint {
  timestamp: string
  value: number
  [key: string]: unknown
}

export interface GEXHistoryPoint {
  timestamp: string
  gex_local: number
  gex_calibrated: number
  put_wall_level: number
  flip_zone_lower: number
  flip_zone_upper: number
}

export interface VIXHistoryPoint {
  timestamp: string
  vix_spot: number
  vx1: number
  vx2: number
  term_structure_ratio: number
  term_structure_state: string
  panic_premium: number
}

export interface DarkpoolHistoryPoint {
  date: string
  dix_value: number
  chartexchange_short_ratio: number
  stockgrid_20d_slope: number
  stockgrid_60d_slope: number
  divergence_flag: boolean
  golden_cross_flag: boolean
  
  v_net: number
  ema_fast_5: number
  ema_slow_20: number
  zero_cross_signal: string | null
  momentum_reversal_signal: string | null
}

// --- 信号 ---
export interface SignalRecord {
  id: number
  trigger_time: string
  total_score: number
  alert_level: AlertLevel
  dimension_scores: Record<string, number>
  hawkes_branching_ratio: number
  acknowledged: boolean
  trigger_count: number
}

// --- 告警 ---
export interface AlertRecord {
  id: number
  trigger_time: string
  total_score: number
  alert_level: AlertLevel
  dimension_scores: Record<string, number>
  resonance_pct: number
  hawkes_branching_ratio: number
  acknowledged: boolean
}

// --- Incident (事件聚合) ---


// --- 系统状态 ---
export interface CircuitBreakerStates {
  [source: string]: 'CLOSED' | 'OPEN' | 'HALF_OPEN'
}

export interface DegradationDetails {
  failed_sources: string[]
  circuit_breaker_states: CircuitBreakerStates
}

export interface SourceStatus {
  name: string
  status: 'ONLINE' | 'DEGRADED' | 'OFFLINE'
  method: string
  availability_pct: number
  failure_count: number
  last_updated: string | null
  last_elapsed_sec?: number | null
  last_error?: string | null
}

export interface SystemStatusData {
  sources: SourceStatus[]
  degradation_mode: boolean
  degradation_details: DegradationDetails
  scheduler_running: boolean
  db_size_mb: number
  last_backup_time: string
  auto_polling_enabled: boolean
  mode: string
  last_manual_collect: string | null
  last_collect_summary: string | null
}

// --- 分页 ---
export interface PaginatedResponse<T> {
  data: T[]
  total: number
  page: number
  page_size: number
}

// --- 配置 ---
export interface AppConfig {
  thresholds: Record<string, number>
  fetch_intervals: {
    intraday: number
    crypto: number
    after_hours: number
  }
  notifications: {
    email_recipients: string
    telegram_bot_token: string
    telegram_chat_id: string
    discord_webhook: string
  }
  cooldown_minutes: number
}

export interface ConfigAuditEntry {
  timestamp: string
  user: string
  field: string
  old_value: string
  new_value: string
}

// --- 通知 ---
export interface NotificationChannel {
  name: string
  connected: boolean
  last_test: string | null
}

export interface NotificationConfig {
  cooldown_minutes: number
  dnd_start: string | null
  dnd_end: string | null
  min_interval_same_level: number
}

// --- 告警 Incident ---
export interface Incident {
  id: number
  title: string
  start_time: string
  end_time: string | null
  highest_level: AlertLevel
  highest_score: number
  trigger_count: number
  reviewed: boolean
}

export interface IncidentTrigger {
  id: number
  trigger_time: string
  alert_level: AlertLevel
  total_score: number
  dimension_names: string[]
}

export interface IncidentDetail extends Incident {
  triggers: IncidentTrigger[]
}

// --- Ticker ---
export interface TickerInfo {
  symbol: string
  name: string
}

// --- 手动采集 ---
export interface ManualCollectSourceResult {
  name: string
  status: 'success' | 'empty' | 'error'
  elapsed_sec: number
  error?: string
  data?: unknown
}

export interface ManualCollectResult {
  ok: boolean
  summary: string
  success_count: number
  total_sources: number
  total_elapsed_sec: number
  sources: ManualCollectSourceResult[]
  collected_at: string
  auto_polling_enabled: boolean
}

// --- 自动轮询 ---
export interface AutoPollingStatus {
  enabled: boolean
  mode?: string
}
