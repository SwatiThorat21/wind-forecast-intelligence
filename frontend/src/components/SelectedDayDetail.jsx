import { ChevronDown } from 'lucide-react'
import { formatDate, formatDeliveryHour, formatMetric, formatSigned, formatTimestamp } from '../utils/formatters.js'

function MiniMetric({ label, value }) {
  return <div className="mini-metric"><span>{label}</span><strong>{value}</strong></div>
}

export default function SelectedDayDetail({ analysis }) {
  if (!analysis) return null
  const { metrics = {}, coverage = {}, periods = [] } = analysis

  return (
    <section className="section-card day-detail" aria-labelledby="detail-title">
      <div className="detail-header">
        <div>
          <p className="eyebrow">Selected-day detail</p>
          <h2 id="detail-title">{formatDate(analysis.decisionDate)} decision</h2>
          <p>Delivery {formatDate(analysis.deliveryDate)} · Cutoff {analysis.cutoff} Europe/London</p>
        </div>
        <div className="coverage-pill">
          <strong>{coverage.matchedPeriods ?? 0}/{coverage.expectedPeriods ?? 0}</strong>
          <span>hours matched</span>
        </div>
      </div>

      <div className="mini-metric-grid">
        <MiniMetric label="Daily MAE" value={formatMetric(metrics.mae, 'MW')} />
        <MiniMetric label="Daily RMSE" value={formatMetric(metrics.rmse, 'MW')} />
        <MiniMetric label="Daily bias" value={formatMetric(metrics.bias, 'MW')} />
        <MiniMetric label="Daily WAPE" value={formatMetric(metrics.wape, '%')} />
      </div>

      <details className="hourly-details" open>
        <summary>Hourly delivery record <ChevronDown size={17} aria-hidden="true" /></summary>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Forecast and actual generation by delivery hour</caption>
            <thead>
              <tr>
                <th scope="col">Delivery hour</th>
                <th scope="col">Forecast MW</th>
                <th scope="col">Actual MW</th>
                <th scope="col">Signed error</th>
                <th scope="col">Forecast publication</th>
              </tr>
            </thead>
            <tbody>
              {periods.map((period) => (
                <tr key={period.targetTime}>
                  <td><strong>{formatDeliveryHour(period)}</strong></td>
                  <td>{formatMetric(period.forecastMw, 'MW')}</td>
                  <td>{formatMetric(period.actualMw, 'MW')}</td>
                  <td className={period.errorMw > 0 ? 'error-positive' : period.errorMw < 0 ? 'error-negative' : ''}>{formatSigned(period.errorMw)}</td>
                  <td>{formatTimestamp(period.forecastPublishTime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}
