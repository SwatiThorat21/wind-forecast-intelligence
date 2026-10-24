import { Ban, Clock3, Database, FlaskConical, Info, Waves } from 'lucide-react'

const notes = [
  { icon: Database, title: 'Observed generation', text: 'Actual generation uses national Elexon FUELHH wind outturn.' },
  { icon: Waves, title: 'Forecast history', text: 'Forecasts use Elexon WINDFOR historical publication revisions.' },
  { icon: Clock3, title: 'No look-ahead', text: 'Each hour uses the latest eligible forecast at or before the purchasing cutoff.' },
  { icon: FlaskConical, title: 'Hourly actuals', text: 'Actual MW is the mean of two complete half-hour readings at HH:00 and HH:30.' },
  { icon: Ban, title: 'No invented data', text: 'Missing observations are not zero-filled, interpolated, or forward-filled.' },
  { icon: Info, title: 'Scope limits', text: 'WINDFOR interval semantics remain an assumption. Prices and financial impact are not included.' },
]

export default function Methodology() {
  return (
    <section className="methodology" aria-labelledby="methodology-title">
      <div className="methodology-heading">
        <p className="eyebrow">Auditability</p>
        <h2 id="methodology-title">Methodology & limitations</h2>
        <p>Designed to make every procurement-time comparison reproducible.</p>
      </div>
      <div className="methodology-grid">
        {notes.map(({ icon: Icon, title, text }) => (
          <article key={title}>
            <Icon size={19} aria-hidden="true" />
            <div><h3>{title}</h3><p>{text}</p></div>
          </article>
        ))}
      </div>
    </section>
  )
}
