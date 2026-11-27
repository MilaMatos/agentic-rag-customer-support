export const API_BASE = 'http://localhost:8000';
export const WS_BASE = 'ws://localhost:8000';
export const DEFAULT_TENANT = 'default-local';

async function apiFetch(path, options = {}, tenantId = DEFAULT_TENANT) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': tenantId,
      ...(options.headers || {}),
    },
  });

  if (!res.ok) {
    let errMsg = `Erro HTTP ${res.status}`;
    try {
      const data = await res.json();
      errMsg = data?.detail?.message || data?.detail || errMsg;
    } catch {
      // ignora erro de parse
    }
    throw new Error(errMsg);
  }
  return res.json();
}

export const api = {
  // Sessões
  createSession: (customerName, tenantId = DEFAULT_TENANT) =>
    apiFetch(
      '/api/v1/sessions',
      { method: 'POST', body: JSON.stringify({ customer_name: customerName }) },
      tenantId
    ),

  listSessions: (statusFilter = '', tenantId = DEFAULT_TENANT) => {
    const q = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : '';
    return apiFetch(`/api/v1/sessions${q}`, {}, tenantId);
  },

  getMessages: (sessionId, view = 'client', tenantId = DEFAULT_TENANT) =>
    apiFetch(`/api/v1/sessions/${sessionId}/messages?view=${view}`, {}, tenantId),

  sendClientMessage: (sessionId, content, tenantId = DEFAULT_TENANT) =>
    apiFetch(
      `/api/v1/sessions/${sessionId}/messages`,
      { method: 'POST', body: JSON.stringify({ content }) },
      tenantId
    ),

  confirmSuggestion: (sessionId, suggestionId, payload, tenantId = DEFAULT_TENANT) =>
    apiFetch(
      `/api/v1/sessions/${sessionId}/suggestions/${suggestionId}/confirm`,
      { method: 'POST', body: JSON.stringify(payload) },
      tenantId
    ),

  closeByAgent: (sessionId, tenantId = DEFAULT_TENANT) =>
    apiFetch(`/api/v1/sessions/${sessionId}/close`, { method: 'POST' }, tenantId),

  closeByClient: (sessionId, tenantId = DEFAULT_TENANT) =>
    apiFetch(`/api/v1/sessions/${sessionId}/client-close`, { method: 'POST' }, tenantId),

  // Especialista N2/N3
  listSpecialistQueue: (tenantId = DEFAULT_TENANT) =>
    apiFetch('/api/v1/specialist/queue', {}, tenantId),

  getSpecialistDossier: (sessionId, tenantId = DEFAULT_TENANT) =>
    apiFetch(`/api/v1/specialist/sessions/${sessionId}`, {}, tenantId),

  sendSpecialistMessage: (sessionId, content, tenantId = DEFAULT_TENANT) =>
    apiFetch(
      `/api/v1/specialist/sessions/${sessionId}/messages`,
      { method: 'POST', body: JSON.stringify({ content }) },
      tenantId
    ),

  resolveBySpecialist: (sessionId, tenantId = DEFAULT_TENANT) =>
    apiFetch(`/api/v1/specialist/sessions/${sessionId}/resolve`, { method: 'POST' }, tenantId),

  // WebSockets
  wsClientUrl: (sessionId, tenantId = DEFAULT_TENANT) =>
    `${WS_BASE}/ws/client/${sessionId}?tenant_id=${encodeURIComponent(tenantId)}`,
  wsAgentUrl: (tenantId = DEFAULT_TENANT) =>
    `${WS_BASE}/ws/agent?tenant_id=${encodeURIComponent(tenantId)}`,
  wsSpecialistUrl: (tenantId = DEFAULT_TENANT) =>
    `${WS_BASE}/ws/specialist?tenant_id=${encodeURIComponent(tenantId)}`,
};

export function getInitials(name = '') {
  const parts = (name || 'CL').trim().split(/\s+/);
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || parts[0]?.[1] || '')).toUpperCase() || 'CL';
}

export function formatTime(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}