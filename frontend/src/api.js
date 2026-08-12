const API_ROOT = (import.meta.env.VITE_API_ROOT || '').replace(/\/$/, '')

function cookieValue(name) {
  const prefix = `${encodeURIComponent(name)}=`
  const item = document.cookie.split('; ').find((part) => part.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : ''
}

async function request(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase()
  const csrfToken = !['GET', 'HEAD', 'OPTIONS'].includes(method) ? cookieValue('workbench_csrf') : ''
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    cache: method === 'GET' ? 'no-store' : options.cache,
    credentials: 'include',
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    let message = '操作失败，请稍后重试'
    try {
      const body = await response.json()
      message = body.detail || message
    } catch {
      // Keep the friendly fallback message.
    }
    if (response.status === 401) window.dispatchEvent(new Event('workbench:unauthorized'))
    const error = new Error(message)
    error.status = response.status
    throw error
  }
  return response.json()
}

export const api = {
  me: () => request('/api/auth/me'),
  setupStatus: () => request('/api/auth/setup-status'),
  setup: (payload) => request('/api/auth/setup', { method: 'POST', body: JSON.stringify(payload) }),
  login: (username, password) => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  register: (payload) => request('/api/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  changePassword: (currentPassword, newPassword) => request('/api/account/password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
  changeUsername: (currentPassword, newUsername) => request('/api/account/username', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_username: newUsername }) }),
  createRegistrationInvite: (expiresInHours = 72) => request('/api/account/invites', { method: 'POST', body: JSON.stringify({ expires_in_hours: expiresInHours }) }),
  issueAgentToken: (currentPassword, confirmation) => request('/api/account/agent-token', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, confirmation }) }),
  deleteAccount: (password, confirmation) => request('/api/account/delete', { method: 'POST', body: JSON.stringify({ password, confirmation }) }),
  dashboard: () => request('/api/dashboard'),
  updateProfile: (payload) => request('/api/settings/profile', { method: 'PUT', body: JSON.stringify(payload) }),
  updateHealthGoals: (payload) => request('/api/settings/health', { method: 'PUT', body: JSON.stringify(payload) }),
  updateIPPreferences: (payload) => request('/api/settings/ip', { method: 'PUT', body: JSON.stringify(payload) }),
  projects: (includeDeleted = false) => request(`/api/projects?include_deleted=${includeDeleted}`),
  createProject: (payload) => request('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  updateProject: (id, payload) => request(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteProject: (id) => request(`/api/projects/${id}`, { method: 'DELETE' }),
  deletedProjects: () => request('/api/projects/deleted'),
  restoreProject: (id) => request(`/api/projects/${id}/restore`, { method: 'POST' }),
  projectPlan: (id, includeDeleted = false) => request(`/api/projects/${id}/plan?include_deleted=${includeDeleted}`),
  projectPhases: (id, includeDeleted = false) => request(`/api/projects/${id}/phases?include_deleted=${includeDeleted}`),
  createProjectPhase: (id, payload) => request(`/api/projects/${id}/phases`, { method: 'POST', body: JSON.stringify(payload) }),
  updateProjectPhase: (id, payload) => request(`/api/project-phases/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteProjectPhase: (id) => request(`/api/project-phases/${id}`, { method: 'DELETE' }),
  restoreProjectPhase: (id) => request(`/api/project-phases/${id}/restore`, { method: 'POST' }),
  createTask: (payload) => request('/api/tasks', { method: 'POST', body: JSON.stringify(payload) }),
  updateTask: (id, payload) => request(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteTask: (id) => request(`/api/tasks/${id}`, { method: 'DELETE' }),
  deletedTasks: () => request('/api/tasks/deleted'),
  restoreTask: (id) => request(`/api/tasks/${id}/restore`, { method: 'POST' }),
  calendar: (startDate, endDate) => request(`/api/calendar?${new URLSearchParams({ start_date: startDate, end_date: endDate }).toString()}`),
  recordWater: (ml) => request('/api/health/water', { method: 'POST', body: JSON.stringify({ ml }) }),
  recordWeight: (kg, recordDate = null) => request('/api/health/weight', { method: 'POST', body: JSON.stringify({ kg, record_date: recordDate }) }),
  healthHistory: (range = 30) => {
    const params = new URLSearchParams()
    if (typeof range === 'number') {
      params.set('days', String(range))
    } else if (range?.startDate && range?.endDate) {
      params.set('start_date', range.startDate)
      params.set('end_date', range.endDate)
    } else {
      params.set('days', String(range?.days || 30))
    }
    return request(`/api/health/history?${params.toString()}`)
  },
  healthRecordsPage: (filters = {}) => {
    const params = new URLSearchParams()
    if (filters.startDate) params.set('start_date', filters.startDate)
    if (filters.endDate) params.set('end_date', filters.endDate)
    if (filters.kind) params.set('kind', filters.kind)
    if (filters.status) params.set('status', filters.status)
    params.set('page', String(filters.page || 1))
    params.set('page_size', String(filters.pageSize || 8))
    return request(`/api/health/records/page?${params.toString()}`)
  },
  updateHealthRecord: (id, payload) => request(`/api/health/records/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteHealthRecord: (id) => request(`/api/health/records/${id}`, { method: 'DELETE' }),
  deletedHealthRecords: () => request('/api/health/records/deleted'),
  restoreHealthRecord: (id) => request(`/api/health/records/${id}/restore`, { method: 'POST' }),
  financeCategories: (includeInactive = false) => request(`/api/finance/categories?include_inactive=${includeInactive}`),
  createFinanceCategory: (payload) => request('/api/finance/categories', { method: 'POST', body: JSON.stringify(payload) }),
  updateFinanceCategory: (id, payload) => request(`/api/finance/categories/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  financeAccounts: (includeArchived = false) => request(`/api/finance/accounts?include_archived=${includeArchived}`),
  financeAccountDetail: (id, date) => request(`/api/finance/accounts/${id}/detail?${new URLSearchParams({ date }).toString()}`),
  createFinanceAccount: (payload) => request('/api/finance/accounts', { method: 'POST', body: JSON.stringify(payload) }),
  updateFinanceAccount: (id, payload) => request(`/api/finance/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  financeTransactions: (filters = {}) => {
    const params = new URLSearchParams()
    if (filters.startDate) params.set('start_date', filters.startDate)
    if (filters.endDate) params.set('end_date', filters.endDate)
    if (filters.type) params.set('transaction_type', filters.type)
    if (filters.categoryId) params.set('category_id', filters.categoryId)
    if (filters.accountId) params.set('account_id', filters.accountId)
    if (filters.search) params.set('search', filters.search)
    if (filters.includeDeleted) params.set('include_deleted', 'true')
    params.set('page', String(filters.page || 1))
    params.set('page_size', String(filters.pageSize || 12))
    return request(`/api/finance/transactions?${params.toString()}`)
  },
  createFinanceTransaction: (payload) => request('/api/finance/transactions', { method: 'POST', body: JSON.stringify(payload) }),
  updateFinanceTransaction: (id, payload) => request(`/api/finance/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteFinanceTransaction: (id) => request(`/api/finance/transactions/${id}`, { method: 'DELETE' }),
  restoreFinanceTransaction: (id) => request(`/api/finance/transactions/${id}/restore`, { method: 'POST' }),
  financeSummary: (startDate, endDate) => request(`/api/finance/summary?${new URLSearchParams({ start_date: startDate, end_date: endDate }).toString()}`),
  financeArchive: (startMonth, endMonth) => request(`/api/finance/archive?${new URLSearchParams({ start_month: startMonth, end_month: endMonth }).toString()}`),
  financeBudgets: (startDate, endDate) => {
    const params = new URLSearchParams()
    if (startDate && endDate) {
      params.set('start_date', startDate)
      params.set('end_date', endDate)
    }
    return request(`/api/finance/budgets?${params.toString()}`)
  },
  upsertFinanceBudget: (payload) => request('/api/finance/budgets', { method: 'PUT', body: JSON.stringify(payload) }),
  deleteFinanceBudget: (id) => request(`/api/finance/budgets/${id}`, { method: 'DELETE' }),
  financeGoals: () => request('/api/finance/goals'),
  createFinanceGoal: (payload) => request('/api/finance/goals', { method: 'POST', body: JSON.stringify(payload) }),
  updateFinanceGoal: (id, payload) => request(`/api/finance/goals/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  financeInsights: (limit = 20) => request(`/api/finance/insights?limit=${limit}`),
  systemInfo: () => request('/api/system/info'),
  backups: () => request('/api/system/backups'),
  createBackup: (label = 'manual') => request('/api/system/backups', { method: 'POST', body: JSON.stringify({ label }) }),
  restoreBackup: (name) => request(`/api/system/backups/${encodeURIComponent(name)}/restore`, { method: 'POST' }),
  updateStartup: (enabled) => request('/api/system/startup', { method: 'PUT', body: JSON.stringify({ enabled }) }),
  enableRemoteAccess: () => request('/api/system/remote-access', { method: 'POST' }),
  createLearningPlan: (payload) => request('/api/growth/plans', { method: 'POST', body: JSON.stringify(payload) }),
  learningPlans: () => request('/api/growth/plans'),
  learningPlan: (id) => request(`/api/growth/plans/${id}`),
  updateLearningPlan: (id, payload) => request(`/api/growth/plans/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  updateLearningProgress: (id, payload) => request(`/api/growth/plans/${id}/progress`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteLearningPlan: (id) => request(`/api/growth/plans/${id}`, { method: 'DELETE' }),
  deletedLearningPlans: () => request('/api/growth/plans/deleted'),
  restoreLearningPlan: (id) => request(`/api/growth/plans/${id}/restore`, { method: 'POST' }),
  createLibraryItem: (payload) => request('/api/library', { method: 'POST', body: JSON.stringify(payload) }),
  libraryItem: (id) => request(`/api/library/${id}`),
  updateLibraryItem: (id, payload) => request(`/api/library/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  contentItem: (id) => request(`/api/content/${id}`),
  upload: (kind, file, metadata = {}) => {
    const form = new FormData()
    form.append('file', file)
    if (metadata.recordDate) form.append('record_date', metadata.recordDate)
    if (metadata.mealSlot) form.append('meal_slot', metadata.mealSlot)
    return request(`/api/uploads/${kind}`, { method: 'POST', body: form })
  },
}

export function websocketUrl() {
  const configured = import.meta.env.VITE_WS_URL
  if (configured) return configured
  if (API_ROOT.startsWith('http')) return `${API_ROOT.replace(/^http/, 'ws')}/ws`
  return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
}

export function workbenchAssetUrl(assetPath) {
  const encoded = String(assetPath || '').split('/').map(encodeURIComponent).join('/')
  return `${API_ROOT}/api/workbench-assets/${encoded}`
}

export function backupDownloadUrl(name) {
  return `${API_ROOT}/api/system/backups/${encodeURIComponent(name)}`
}
