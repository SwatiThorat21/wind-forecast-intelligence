const numberFormatter = new Intl.NumberFormat('en-GB', {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})

const integerFormatter = new Intl.NumberFormat('en-GB', {
  maximumFractionDigits: 0,
})

export function formatNumber(value, { decimals = 1 } = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return decimals === 0 ? integerFormatter.format(value) : numberFormatter.format(value)
}

export function formatMetric(value, unit, options) {
  const formatted = formatNumber(value, options)
  return formatted === '—' ? formatted : `${formatted} ${unit}`
}

export function formatSigned(value, unit = 'MW') {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatNumber(value)} ${unit}`
}

export function formatDate(value, options = {}) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Europe/London',
    ...options,
  }).format(new Date(`${value}T12:00:00Z`))
}

export function formatTimestamp(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'Europe/London',
  }).format(new Date(value))
}

export function formatDeliveryHour(period) {
  if (period?.targetTimeLocal) return period.targetTimeLocal.slice(11, 16)
  if (!period?.targetTime) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'Europe/London',
  }).format(new Date(period.targetTime))
}

export function coveragePercentage(coverage) {
  if (!coverage?.expectedPeriods) return null
  return (coverage.matchedPeriods / coverage.expectedPeriods) * 100
}
