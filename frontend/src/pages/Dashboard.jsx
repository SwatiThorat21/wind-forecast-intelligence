import { useEffect, useMemo, useState } from 'react'
import { CalendarClock, ShieldCheck } from 'lucide-react'
import { fetchForecast, fetchHealth, fetchSummary } from '../services/api.js'
import Header from '../components/layout/Header.jsx'
import SectionCard from '../components/layout/SectionCard.jsx'
import { ErrorNotice, LoadingBlock } from '../components/layout/Feedback.jsx'
import ExecutiveOverview from '../components/cards/ExecutiveOverview.jsx'
import BusinessInsights from '../components/cards/BusinessInsights.jsx'
import DecisionControls from '../components/filters/DecisionControls.jsx'
import ForecastActualChart from '../components/charts/ForecastActualChart.jsx'
import DailyMaeChart from '../components/charts/DailyMaeChart.jsx'
import BiasChart from '../components/charts/BiasChart.jsx'
import SelectedDayDetail from '../components/SelectedDayDetail.jsx'
import Methodology from '../components/Methodology.jsx'
import { formatDate } from '../utils/formatters.js'

const DEFAULT_DECISION_DATE = '2026-01-14'
const DEFAULT_CUTOFF = '12:00'
const VALID_CUTOFF = /^(?:[01]\d|2[0-3]):[0-5]\d$/

function nextCalendarDate(value) {
  const date = new Date(`${value}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}

export default function Dashboard() {
  const [decisionDate, setDecisionDate] = useState(DEFAULT_DECISION_DATE)
  const [cutoff, setCutoff] = useState(DEFAULT_CUTOFF)
  const [health, setHealth] = useState(null)
  const [summary, setSummary] = useState(null)
  const [daily, setDaily] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [dailyLoading, setDailyLoading] = useState(true)
  const [summaryError, setSummaryError] = useState(null)
  const [dailyError, setDailyError] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth({ signal: controller.signal })
      .then(setHealth)
      .catch((error) => {
        if (error.name !== 'AbortError') setHealth({ historicalDataset: { available: false } })
      })
    return () => controller.abort()
  }, [refreshKey])

  useEffect(() => {
    if (!VALID_CUTOFF.test(cutoff)) return undefined
    const controller = new AbortController()
    setSummaryLoading(true)
    setSummaryError(null)
    fetchSummary(cutoff, { signal: controller.signal })
      .then(setSummary)
      .catch((error) => {
        if (error.name !== 'AbortError') setSummaryError(error)
      })
      .finally(() => {
        if (!controller.signal.aborted) setSummaryLoading(false)
      })
    return () => controller.abort()
  }, [cutoff, refreshKey])

  useEffect(() => {
    if (!decisionDate || !VALID_CUTOFF.test(cutoff)) return undefined
    const controller = new AbortController()
    setDailyLoading(true)
    setDailyError(null)
    fetchForecast(decisionDate, cutoff, { signal: controller.signal })
      .then(setDaily)
      .catch((error) => {
        if (error.name !== 'AbortError') setDailyError(error)
      })
      .finally(() => {
        if (!controller.signal.aborted) setDailyLoading(false)
      })
    return () => controller.abort()
  }, [decisionDate, cutoff, refreshKey])

  const fallbackDeliveryDate = useMemo(() => nextCalendarDate(decisionDate), [decisionDate])
  const partialCoverage = daily && daily.coverage?.matchedPeriods < daily.coverage?.expectedPeriods
  const retry = () => setRefreshKey((value) => value + 1)

  return (
    <div className="app-shell">
      <Header health={health} />
      <main>
        <section className="hero-band" aria-labelledby="dashboard-title">
          <div>
            <div className="hero-badge"><ShieldCheck size={15} /> Cutoff-aware historical analysis</div>
            <h2 id="dashboard-title">See the forecast your procurement team actually had.</h2>
            <p>Compare day-ahead wind expectations with realised generation, without future-information leakage.</p>
          </div>
          <div className="hero-period">
            <CalendarClock size={20} aria-hidden="true" />
            <div><span>Analysis window</span><strong>31 decisions · 744 delivery hours</strong></div>
          </div>
        </section>

        <DecisionControls
          decisionDate={decisionDate}
          cutoff={cutoff}
          deliveryDate={daily?.deliveryDate || fallbackDeliveryDate}
          onDecisionDateChange={setDecisionDate}
          onCutoffChange={setCutoff}
          busy={dailyLoading || summaryLoading}
        />

        <div className="announcer sr-only" aria-live="polite">
          {dailyLoading || summaryLoading ? 'Refreshing dashboard analysis' : `Dashboard updated for ${formatDate(decisionDate)} at ${cutoff}`}
        </div>

        {summaryError && <ErrorNotice message={summaryError.message} onRetry={retry} />}
        {summaryLoading && !summary ? (
          <LoadingBlock label="Loading January portfolio metrics" />
        ) : summary ? (
          <ExecutiveOverview summary={summary} />
        ) : null}

        {summary && <BusinessInsights summary={summary} />}

        {partialCoverage && (
          <div className="feedback partial-feedback" role="status">
            This delivery day has partial coverage: {daily.coverage.matchedPeriods} of {daily.coverage.expectedPeriods} hours are matched. Missing periods remain visible and are excluded from metrics.
          </div>
        )}

        <div className={`dashboard-grid chart-grid main-chart-grid ${dailyLoading ? 'is-updating' : ''}`}>
          <SectionCard
            className="span-two"
            title="Forecast vs actual generation"
            subtitle={`${formatDate(daily?.deliveryDate || fallbackDeliveryDate)} delivery · hourly MW`}
            action={daily?.selectedForecastPublicationTimes?.length ? <span className="publication-chip">Latest selected: {daily.selectedForecastPublicationTimes.at(-1).slice(11, 16)} UTC</span> : null}
          >
            {dailyError ? <ErrorNotice message={dailyError.message} onRetry={retry} /> : dailyLoading && !daily ? <LoadingBlock /> : <ForecastActualChart periods={daily?.periods} />}
          </SectionCard>
        </div>

        <div className="dashboard-grid insights-grid">
          <SectionCard title="Daily accuracy trend" subtitle="Mean absolute error by January decision date">
            {summaryLoading && !summary ? <LoadingBlock /> : <DailyMaeChart days={summary?.dailyAccuracyStatistics} selectedDate={decisionDate} />}
          </SectionCard>
          <SectionCard title="Forecast bias mix" subtitle="Direction of error across matched January hours">
            {summaryLoading && !summary ? <LoadingBlock /> : <BiasChart metrics={summary?.metrics} />}
          </SectionCard>
        </div>

        {dailyError ? null : dailyLoading && !daily ? <LoadingBlock label="Loading selected-day detail" /> : <SelectedDayDetail analysis={daily} />}
        <Methodology />
      </main>
      <footer>
        <span>Wind Forecast Intelligence</span>
        <span>Historical data: Elexon BMRS · January 2026</span>
      </footer>
    </div>
  )
}
