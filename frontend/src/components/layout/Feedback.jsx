import { AlertCircle, RefreshCw } from 'lucide-react'

export function ErrorNotice({ message, onRetry }) {
  return (
    <div className="feedback error-feedback" role="alert">
      <AlertCircle size={20} aria-hidden="true" />
      <div>
        <strong>Analysis unavailable</strong>
        <p>{message}</p>
      </div>
      {onRetry && (
        <button type="button" className="retry-button" onClick={onRetry}>
          <RefreshCw size={15} /> Retry
        </button>
      )}
    </div>
  )
}

export function LoadingBlock({ label = 'Loading analytics' }) {
  return (
    <div className="loading-block" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function EmptyState({ message }) {
  return <div className="empty-state">{message}</div>
}
