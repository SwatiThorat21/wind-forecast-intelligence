import { Database, Wind } from 'lucide-react'

export default function Header({ health }) {
  const isAvailable = health?.historicalDataset?.available
  const statusLabel = isAvailable === false
    ? 'Data unavailable'
    : isAvailable === true
      ? 'Historical data ready'
      : 'Checking data'

  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <Wind size={24} strokeWidth={2.2} />
          </div>
          <div>
            <p className="eyebrow">Procurement intelligence</p>
            <h1>Wind Forecast Intelligence</h1>
            <p className="header-subtitle">UK Day-Ahead Wind Generation Analytics</p>
          </div>
        </div>
        <div className="header-meta" aria-label="Dataset information">
          <span className="meta-chip"><Database size={15} /> Elexon BMRS</span>
          <span className="meta-chip">January 2026</span>
          <span className={`status-chip ${isAvailable === false ? 'status-error' : ''}`}>
            <span className="status-dot" aria-hidden="true" />
            {statusLabel}
          </span>
        </div>
      </div>
    </header>
  )
}
