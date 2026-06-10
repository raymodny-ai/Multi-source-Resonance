/**
 * 格式化大额数字
 * 例如: 150000000 -> "$150M", -5000000 -> "-$5M"
 */
export function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '--'
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  if (abs >= 1_000_000_000) return `${sign}$${(abs / 1_000_000_000).toFixed(1)}B`
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(0)}M`
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`
  return `${sign}$${abs.toFixed(0)}`
}

/**
 * 格式化百分比
 */
export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value == null) return '--'
  return `${value.toFixed(decimals)}%`
}

/**
 * 格式化小数 (保留 N 位)
 */
export function formatDecimal(value: number | null | undefined, decimals = 4): string {
  if (value == null) return '--'
  return value.toFixed(decimals)
}

/**
 * 格式化比率 (如 0.98)
 */
export function formatRatio(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '--'
  return value.toFixed(decimals)
}

/**
 * 格式化 Open Interest (单位转换)
 */
export function formatOI(value: number | null | undefined): string {
  if (value == null) return '--'
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(0)}M`
  return `$${value.toFixed(0)}`
}

/**
 * 格式化股票价格
 */
export function formatPrice(value: number | null | undefined): string {
  if (value == null) return '--'
  return value.toFixed(0)
}

/**
 * 截断小数显示
 */
export function formatCompact(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '--'
  if (Math.abs(value) >= 1000) return value.toFixed(0)
  return value.toFixed(decimals)
}
