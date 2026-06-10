import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import type { TimezoneOption } from '../types/common'

dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

/**
 * 将 ISO 8601 时间戳按指定时区格式化
 * 后端强制返回 ISO 8601 带时区偏移或 UTC
 */
export function formatTime(
  isoTimestamp: string | null | undefined,
  tz: TimezoneOption,
  format = 'HH:mm:ss',
): string {
  if (!isoTimestamp) return '--'
  const resolvedTz = tz === 'local' ? undefined : tz
  const d = dayjs(isoTimestamp)
  if (!d.isValid()) return '--'
  if (resolvedTz) return d.tz(resolvedTz).format(format)
  return d.format(format)
}

/**
 * 格式化为完整的日期时间
 */
export function formatDateTime(
  isoTimestamp: string | null | undefined,
  tz: TimezoneOption,
): string {
  return formatTime(isoTimestamp, tz, 'YYYY-MM-DD HH:mm:ss')
}

/**
 * 相对时间（"2 分钟前"）
 */
export function formatRelativeTime(isoTimestamp: string | null | undefined): string {
  if (!isoTimestamp) return '--'
  const d = dayjs(isoTimestamp)
  if (!d.isValid()) return '--'
  const now = dayjs()
  const diffSeconds = now.diff(d, 'second')

  if (diffSeconds < 60) return `${diffSeconds}秒前`
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}分钟前`
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)}小时前`
  return `${Math.floor(diffSeconds / 86400)}天前`
}

/**
 * 根据时区返回当前日期字符串
 */
export function getCurrentDateStr(tz: TimezoneOption): string {
  const resolvedTz = tz === 'local' ? undefined : tz
  if (resolvedTz) return dayjs().tz(resolvedTz).format('YYYY-MM-DD')
  return dayjs().format('YYYY-MM-DD')
}

/**
 * 解析 ISO 时间戳的时区偏移信息
 */
export function getTimezoneOffset(isoTimestamp: string): string {
  const match = isoTimestamp.match(/([+-]\d{2}:\d{2})|Z$/)
  return match ? match[0] : ''
}
