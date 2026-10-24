import { CalendarDays, Clock3, Truck } from 'lucide-react'
import { formatDate } from '../../utils/formatters.js'

export default function DecisionControls({ decisionDate, cutoff, deliveryDate, onDecisionDateChange, onCutoffChange, busy }) {
  return (
    <section className="control-panel" aria-labelledby="controls-title">
      <div className="control-intro">
        <p className="eyebrow">Decision reconstruction</p>
        <h2 id="controls-title">Purchasing parameters</h2>
        <p>Recreate the information available when the day-ahead decision was made.</p>
      </div>
      <div className="control-fields">
        <label className="control-field">
          <span><CalendarDays size={16} /> Decision date</span>
          <input
            type="date"
            min="2026-01-01"
            max="2026-01-31"
            value={decisionDate}
            onChange={(event) => onDecisionDateChange(event.target.value)}
          />
        </label>
        <label className="control-field">
          <span><Clock3 size={16} /> Purchasing cutoff</span>
          <input
            type="time"
            step="60"
            value={cutoff}
            onChange={(event) => onCutoffChange(event.target.value)}
          />
          <small>Europe/London</small>
        </label>
        <div className="delivery-field" aria-live="polite">
          <span><Truck size={16} /> Delivery date</span>
          <strong>{formatDate(deliveryDate)}</strong>
          <small>{busy ? 'Refreshing analysis…' : 'Next calendar day'}</small>
        </div>
      </div>
    </section>
  )
}
