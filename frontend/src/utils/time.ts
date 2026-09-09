export function relativeTime(value: string | null | undefined): string {
  if (!value) return ''
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return ''
  const deltaSeconds = Math.round((time - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' })
  const absolute = Math.abs(deltaSeconds)
  if (absolute < 60) return '刚刚'
  if (absolute < 3600) return formatter.format(Math.round(deltaSeconds / 60), 'minute')
  if (absolute < 86400) return formatter.format(Math.round(deltaSeconds / 3600), 'hour')
  if (absolute < 604800) return formatter.format(Math.round(deltaSeconds / 86400), 'day')
  return new Date(time).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

export function fullTime(value: string | null | undefined): string {
  if (!value) return ''
  const time = new Date(value)
  if (Number.isNaN(time.getTime())) return ''
  return time.toLocaleString('zh-CN', { hour12: false })
}
