import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { EmptyState } from '../layout/Feedback.jsx'
import { formatNumber } from '../../utils/formatters.js'

function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="chart-tooltip compact-tooltip">
      <strong>{row.label}</strong>
      <span>Daily MAE <b>{formatNumber(row.mae)} MW</b></span>
      <small>{row.matched} matched hours</small>
    </div>
  )
}

export default function DailyMaeChart({ days = [], selectedDate }) {
  const data = days.map((day) => ({
    date: day.decisionDate,
    day: Number(day.decisionDate.slice(-2)),
    label: `Decision ${day.decisionDate.slice(-2)} Jan`,
    mae: day.metrics?.mae,
    matched: day.coverage?.matchedPeriods,
  }))
  if (!data.length || !data.some((day) => day.mae != null)) {
    return <EmptyState message="No daily accuracy statistics are available." />
  }

  return (
    <div className="chart-container chart-container-small" role="img" aria-label="January daily mean absolute error trend">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 10, right: 8, left: 0, bottom: 0 }} accessibilityLayer>
          <CartesianGrid stroke="#E7ECF2" strokeDasharray="3 5" vertical={false} />
          <XAxis dataKey="day" tick={{ fill: '#65758B', fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#DCE3EB' }} interval={3} />
          <YAxis tick={{ fill: '#65758B', fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(value) => `${Math.round(value / 1000)}k`} width={40} />
          <Tooltip content={<TrendTooltip />} />
          <Bar dataKey="mae" name="Daily MAE" fill="#42A79D" radius={[3, 3, 0, 0]} maxBarSize={18}>
            {data.map((row) => (
              <Cell key={row.date} fill={row.date === selectedDate ? '#14243A' : '#42A79D'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="chart-axis-caption">Decision date · January 2026</div>
      {selectedDate && <span className="sr-only">Currently selected decision date: {selectedDate}</span>}
    </div>
  )
}
