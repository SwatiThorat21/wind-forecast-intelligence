export default function SectionCard({ title, subtitle, action, className = '', children }) {
  return (
    <section className={`section-card ${className}`}>
      {(title || action) && (
        <div className="section-heading">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action && <div className="section-action">{action}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
