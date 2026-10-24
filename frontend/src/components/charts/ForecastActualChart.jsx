import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { EmptyState } from '../layout/Feedback.jsx'
import { formatDeliveryHour, formatNumber, formatSigned } from '../../utils/formatters.js'

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  return (
    <div className="chart-tooltip">
      <strong>Delivery {label}</strong>
      <span><i className="legend-swatch swatch-forecast" /> Forecast <b>{formatNumber(row.forecastMw)} MW</b></span>
      <span><i className="legend-swatch swatch-actual" /> Actual <b>{formatNumber(row.actualMw)} MW</b></span>
      <span className={row.errorMw > 0 ? 'error-positive' : row.errorMw < 0 ? 'error-negative' : ''}>
        Signed error <b>{formatSigned(row.errorMw)}</b>
      </span>
      <small>Absolute error {row.errorMw == null ? '—' : `${formatNumber(Math.abs(row.errorMw))} MW`}</small>
    </div>
  )
}

export default function ForecastActualChart({ periods = [] }) {
  if (!periods.length) return <EmptyState message="No hourly records are available for this delivery date." />
  if (!periods.some((period) => period.forecastMw != null || period.actualMw != null)) {
    return <EmptyState message="Hourly records contain no forecast or actual generation values." />
  }
  const data = periods.map((period) => ({
    ...period,
    hour: formatDeliveryHour(period),
  }))

  return (
    <div className="chart-container" role="img" aria-label="Hourly wind forecast and actual generation line chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 14, left: 0, bottom: 0 }} accessibilityLayer>
          <CartesianGrid stroke="#E7ECF2" strokeDasharray="4 5" vertical={false} />
          <XAxis dataKey="hour" tick={{ fill: '#65758B', fontSize: 12 }} tickLine={false} axisLine={{ stroke: '#DCE3EB' }} interval={2} />
          <YAxis
            tick={{ fill: '#65758B', fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => `${Math.round(value / 1000)}k`}
            width={46}
            label={{ value: 'MW', angle: -90, position: 'insideLeft', fill: '#65758B', fontSize: 11 }}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#9AA8B9', strokeDasharray: '3 3' }} />
          <Legend iconType="plainline" wrapperStyle={{ paddingTop: 12, color: '#43536A', fontSize: 13 }} />
          <Line
            type="monotone"
            dataKey="forecastMw"
            name="Forecast"
            stroke="#0D9488"
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 4, fill: '#0D9488', stroke: '#FFFFFF', strokeWidth: 2 }}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="actualMw"
            name="Actual"
            stroke="#14243A"
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 4, fill: '#14243A', stroke: '#FFFFFF', strokeWidth: 2 }}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
