import {
  Area,
  AreaChart,
  CartesianGrid,
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
  if (!data.length) return <EmptyState message="No daily accuracy statistics are available." />

  return (
    <div className="chart-container chart-container-small" role="img" aria-label="January daily mean absolute error trend">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 10, left: 0, bottom: 0 }} accessibilityLayer>
          <defs>
            <linearGradient id="maeFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0D9488" stopOpacity={0.24} />
              <stop offset="100%" stopColor="#0D9488" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#E7ECF2" strokeDasharray="4 5" vertical={false} />
          <XAxis dataKey="day" tick={{ fill: '#65758B', fontSize: 12 }} tickLine={false} axisLine={{ stroke: '#DCE3EB' }} interval={4} />
          <YAxis tick={{ fill: '#65758B', fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(value) => `${Math.round(value / 1000)}k`} width={42} />
          <Tooltip content={<TrendTooltip />} />
          <Area type="monotone" dataKey="mae" stroke="#0D9488" strokeWidth={2.5} fill="url(#maeFill)" connectNulls={false} activeDot={{ r: 5, fill: '#0D9488', stroke: '#FFFFFF', strokeWidth: 2 }} />
        </AreaChart>
      </ResponsiveContainer>
      <div className="chart-axis-caption">Decision date · January 2026</div>
      {selectedDate && <span className="sr-only">Currently selected decision date: {selectedDate}</span>}
    </div>
  )
}
