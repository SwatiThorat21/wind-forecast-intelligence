const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, { status = null, code = 'request_failed' } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function apiUrl(resource, params = {}) {
  const root = configuredBaseUrl.endsWith('/api')
    ? configuredBaseUrl
    : `${configuredBaseUrl}/api`
  const query = new URLSearchParams(params).toString()
  return `${root}/${resource}${query ? `?${query}` : ''}`
}

async function request(resource, { params, signal } = {}) {
  let response
  try {
    response = await fetch(apiUrl(resource, params), {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError(
      'Unable to reach the analysis service. Confirm that the Flask backend is running.',
      { code: 'network_error' },
    )
  }

  let body = null
  try {
    body = await response.json()
  } catch {
    throw new ApiError('The analysis service returned an unreadable response.', {
      status: response.status,
      code: 'invalid_response',
    })
  }

  if (!response.ok) {
    throw new ApiError(
      body?.error?.message || `The analysis request failed with HTTP ${response.status}.`,
      { status: response.status, code: body?.error?.code || 'http_error' },
    )
  }
  return body
}

export const fetchHealth = ({ signal } = {}) => request('health', { signal })

export const fetchSummary = (cutoff, { signal } = {}) =>
  request('summary', { params: { cutoff }, signal })

export const fetchForecast = (decisionDate, cutoff, { signal } = {}) =>
  request('forecast', {
    params: { decision_date: decisionDate, cutoff },
    signal,
  })
