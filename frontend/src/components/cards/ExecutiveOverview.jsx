import { Activity, Gauge, Percent, Scale, Target } from 'lucide-react'
import { coveragePercentage, formatMetric } from '../../utils/formatters.js'
import KpiCard from './KpiCard.jsx'

function biasDescription(bias) {
  if (bias === null || bias === undefined) return 'Unavailable for the selected coverage'
  if (bias > 0) return 'Positive: forecasts tend to overestimate actual generation'
  if (bias < 0) return 'Negative: forecasts tend to underestimate actual generation'
  return 'Forecast and actual generation are balanced on average'
}

export default function ExecutiveOverview({ summary }) {
  const metrics = summary?.metrics || {}
  const coverage = coveragePercentage(summary?.coverage)

  const cards = [
    { icon: Target, label: 'MAE', value: formatMetric(metrics.mae, 'MW'), detail: 'Average absolute hourly forecast error' },
    { icon: Activity, label: 'RMSE', value: formatMetric(metrics.rmse, 'MW'), detail: 'Penalises larger forecast misses', tone: 'navy' },
    { icon: Scale, label: 'Forecast Bias', value: formatMetric(metrics.bias, 'MW'), detail: biasDescription(metrics.bias), tone: metrics.bias > 0 ? 'amber' : 'teal' },
    { icon: Percent, label: 'WAPE', value: formatMetric(metrics.wape, '%'), detail: 'Absolute error relative to actual generation' },
    { icon: Gauge, label: 'Data Coverage', value: formatMetric(coverage, '%'), detail: `${summary?.coverage?.matchedPeriods ?? '—'} of ${summary?.coverage?.expectedPeriods ?? '—'} expected hourly periods matched`, tone: 'green' },
  ]

  return (
    <section aria-labelledby="overview-title">
      <div className="content-heading">
        <div>
          <p className="eyebrow">January portfolio view</p>
          <h2 id="overview-title">Executive overview</h2>
        </div>
        <p className="heading-note">Metrics use every valid matched hour at the selected cutoff.</p>
      </div>
      <div className="kpi-grid">
        {cards.map((card) => <KpiCard key={card.label} {...card} />)}
      </div>
    </section>
  )
}
