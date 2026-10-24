export default function KpiCard({ icon: Icon, label, value, detail, tone = 'teal' }) {
  return (
    <article className={`kpi-card kpi-${tone}`}>
      <div className="kpi-topline">
        <span className="kpi-icon" aria-hidden="true"><Icon size={18} /></span>
        <span className="kpi-label">{label}</span>
      </div>
      <strong className="kpi-value">{value}</strong>
      <p>{detail}</p>
    </article>
  )
}
