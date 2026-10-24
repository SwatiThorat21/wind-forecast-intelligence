import { Gauge, Lightbulb, Scale } from 'lucide-react'
import { coveragePercentage, formatMetric, formatNumber, formatSigned } from '../../utils/formatters.js'

function biasMessage(bias) {
  if (bias === null || bias === undefined) return 'Average bias is unavailable at this cutoff.'
  if (bias > 0) return `Average forecast bias was ${formatSigned(bias)} at the selected cutoff.`
  if (bias < 0) return `Average forecast bias was ${formatSigned(bias)} at the selected cutoff.`
  return 'Average forecast bias was neutral at the selected cutoff.'
}

export default function BusinessInsights({ summary }) {
  if (!summary) return null
  const metrics = summary.metrics || {}
  const matched = metrics.matchedPeriodCount ?? summary.coverage?.matchedPeriods ?? 0
  const overforecast = metrics.overforecastCount ?? 0
  const coverage = coveragePercentage(summary.coverage)

  const insights = [
    {
      icon: Lightbulb,
      label: 'Direction of error',
      value: `${formatNumber(overforecast, { decimals: 0 })} of ${formatNumber(matched, { decimals: 0 })} hours`,
      text: 'were overforecast across the January decision window.',
    },
    {
      icon: Scale,
      label: 'Average bias',
      value: formatMetric(metrics.bias, 'MW'),
      text: biasMessage(metrics.bias),
    },
    {
      icon: Gauge,
      label: 'Matched coverage',
      value: formatMetric(coverage, '%'),
      text: `${summary.coverage?.matchedPeriods ?? 0} matched of ${summary.coverage?.expectedPeriods ?? 0} expected hours.`,
    },
  ]

  return (
    <section className="business-insights" aria-labelledby="business-insights-title">
      <div className="insight-heading">
        <p className="eyebrow">Procurement readout</p>
        <h2 id="business-insights-title">What this cutoff tells you</h2>
      </div>
      <div className="insight-list">
        {insights.map(({ icon: Icon, label, value, text }) => (
          <article key={label}>
            <span className="insight-icon" aria-hidden="true"><Icon size={17} /></span>
            <div>
              <span>{label}</span>
              <strong>{value}</strong>
              <p>{text}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
