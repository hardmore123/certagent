// API 客户端：统一 Bearer 注入 + 401 拦截

const BASE = '/api/v1'

function getToken(): string | null {
  return localStorage.getItem('token')
}

export function setToken(token: string) {
  localStorage.setItem('token', token)
}

export function clearToken() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
}

export function getUser(): { username: string; role: string } | null {
  const raw = localStorage.getItem('user')
  return raw ? JSON.parse(raw) : null
}

export function setUser(user: { username: string; role: string }) {
  localStorage.setItem('user', JSON.stringify(user))
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (init?.body && !(init.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> || {}) },
  })

  if (resp.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('未授权')
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail || resp.statusText)
  }
  return resp.json() as Promise<T>
}

// === API 方法 ===

export async function login(username: string, password: string) {
  const data = await request<{ token: string; user: { username: string; role: string } }>(
    '/auth/login',
    { method: 'POST', body: JSON.stringify({ username, password }) }
  )
  setToken(data.token)
  setUser(data.user)
  return data
}

export async function createJob(fileOrig: File, filePlm: File, fuzzyLlm = false) {
  const form = new FormData()
  form.append('file_orig', fileOrig)
  form.append('file_plm', filePlm)
  form.append('fuzzy_llm', fuzzyLlm ? 'true' : 'false')
  return request<{ job_id: string; status: string }>('/jobs', { method: 'POST', body: form })
}

export async function listJobs() {
  return request<Array<{
    job_id: string; status: string; stage: string; progress: number;
    file_orig: string; file_plm: string; diff_count: number; error: string;
  }>>('/jobs')
}

export async function getJob(id: string) {
  return request<{
    job_id: string; status: string; stage: string; progress: number;
    diff_count: number; error: string;
  }>(`/jobs/${id}`)
}

export interface MemoryHint {
  signature: string; accepts: number; rejects: number; total: number;
  dominant: string; last_verdict: string; last_reason: string;
}

export async function getDiffs(id: string) {
  return request<Array<{
    key: string; type: string; table: number; confidence: string;
    output_index: number; group: string;
    关键件名称: string; 型号: string; 规格材料: string; 制造商: string;
    生产企业: string; 认证标准: string; 证书号: string;
    changed_fields: string[]; source_label: string; action: string; reason: string;
    pair_reason: string; pair_confidence: number;
    memory_applied?: boolean; memory?: MemoryHint | null;
    a_row: Record<string, any> | null; b_row: Record<string, any> | null;
  }>>(`/jobs/${id}/diffs`)
}

// 决策载荷：字符串(简单裁决) 或 明细对象(手动匹配需 target_key)
export type DecisionPayload =
  | string
  | { verdict: string; target_key?: string; reason?: string }

export async function submitDecisions(
  id: string,
  decisions: Record<string, DecisionPayload>,
  reasons?: Record<string, string>,
) {
  return request<{ status: string }>(`/jobs/${id}/decisions`, {
    method: 'POST',
    body: JSON.stringify({ decisions, reasons: reasons || {} }),
  })
}

export interface AuditReport {
  status: string // ok | warning | critical
  input_orig_rows: number
  input_plm_rows: number
  diff_count: number
  type_counts: Record<string, number>
  a_conserved: boolean
  b_conserved: boolean
  kept_count: number
  output_rows: number
  output_mismatch: number
  lost_orig: Array<Record<string, any>>
  lost_plm: Array<Record<string, any>>
  missing_in_output: Array<Record<string, any>>
  rejected_rows: number
  same_changed_rejected: number
  repaired: boolean
  recommendations: string[]
  details: string[]
}

export async function getResult(id: string) {
  return request<{
    job_id: string
    changes: Array<{ 变更项目: string; 变更前: string; 变更后: string }>
    diff_summary: Record<string, number>
    audit: AuditReport | null
  }>(`/jobs/${id}/result`)
}
