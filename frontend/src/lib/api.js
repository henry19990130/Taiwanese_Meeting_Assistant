const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const api = {
  base: API_BASE,
  async request(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    })
    if (!response.ok) throw new Error(`API Error: ${response.status}`)
    return response.json()
  },
  meetings: {
    list: () => api.request('/api/meetings'),
    create: (data) => api.request('/api/meetings', { method: 'POST', body: JSON.stringify(data) }),
    get: (id) => api.request(`/api/meetings/${id}`),
    delete: (id) => api.request(`/api/meetings/${id}`, { method: 'DELETE' }),
  },
  asr: {
    upload: (formData) => fetch(`${API_BASE}/api/asr/upload`, { method: 'POST', body: formData }),
  },
  assistant: {
    query: (question, meetingId) => api.request('/api/assistant/query', {
      method: 'POST',
      body: JSON.stringify({ question, meeting_id: meetingId }),
    }),
  },
}