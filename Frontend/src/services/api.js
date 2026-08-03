const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

export async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const payload = await response.json()
      message = payload.detail || payload.message || message
    } catch {
      // Keep the HTTP fallback when a proxy returns a non-JSON error.
    }
    throw new Error(message)
  }
  return response
}

export { API_BASE }
