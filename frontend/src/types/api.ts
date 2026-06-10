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
  }
  hawkes: HawkesResult
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
export interface IncidentRecord {
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

// --- 系统状态 ---
export interface SourceStatus {
  name: string
  status: 'ONLINE' | 'DEGRADED' | 'OFFLINE'
  availability_pct: number
  failure_count: number
  last_updated: string
}

export interface SystemStatusData {
  sources: SourceStatus[]
  degradation_mode: boolean
  scheduler_running: boolean
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
    after_hours: number
  }
  notifications: {
    email_recipients: string[]
    telegram_token: string
    telegram_chat_id: string
    discord_webhook: string
  }
  cooldown_minutes: number
}
