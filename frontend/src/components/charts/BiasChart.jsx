import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { formatNumber } from '../../utils/formatters.js'

const COLORS = ['#C88732', '#3F6F8F', '#7AA99F']

function BiasTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip compact-tooltip">
      <strong>{payload[0].name}</strong>
      <span><b>{formatNumber(payload[0].value, { decimals: 0 })}</b> hourly periods</span>
    </div>
  )
}

export default function BiasChart({ metrics = {} }) {
  const data = [
    { name: 'Overforecast', value: metrics.overforecastCount || 0 },
    { name: 'Underforecast', value: metrics.underforecastCount || 0 },
    { name: 'Exact match', value: metrics.exactMatchCount || 0 },
  ]
  const total = data.reduce((sum, item) => sum + item.value, 0)

  return (
    <div className="bias-layout">
      <div className="bias-donut" role="img" aria-label="Distribution of overforecast, underforecast, and exact match hours">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="66%" outerRadius="91%" paddingAngle={total ? 2 : 0} stroke="none">
              {data.map((entry, index) => <Cell key={entry.name} fill={COLORS[index]} />)}
            </Pie>
            <Tooltip content={<BiasTooltip />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center"><strong>{formatNumber(total, { decimals: 0 })}</strong><span>matched hours</span></div>
      </div>
      <div className="bias-legend">
        {data.map((item, index) => (
          <div key={item.name}>
            <span className="bias-color" style={{ background: COLORS[index] }} aria-hidden="true" />
            <span>{item.name}</span>
            <strong>{formatNumber(item.value, { decimals: 0 })}</strong>
          </div>
        ))}
        <p><b>Positive bias</b> means forecast exceeds actual. <b>Negative bias</b> means forecast is below actual.</p>
      </div>
    </div>
  )
}
