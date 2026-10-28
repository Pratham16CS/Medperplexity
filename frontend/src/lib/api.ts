import type {
  AssessmentHistoryItem,
  AuditEventItem,
  ClinicalResponse,
  HospitalUser,
  MedicationCatalogItem,
  Patient,
  ResearchPaper,
  SavedPaper,
} from '../types/clinical'

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '')

const TOKEN_STORAGE_KEY = 'medperplexity_auth_token'

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch {
    // Ignore storage errors in restricted contexts
  }
}

type ApiPatient = {
  patient_id: string
  name?: string | null
  age?: number | null
  sex?: string | null
  conditions?: string[]
  allergies?: string[]
  current_medications?: string[]
  assigned_doctor_id?: string
  assigned_doctor_name?: string
  department?: string
  specialty?: string
  room_bed?: string
  admission_status?: string
}

function mapPatient(raw: ApiPatient): Patient {
  const name = raw.name || 'Unnamed patient'
  const conditions = raw.conditions ?? []
  const medications = raw.current_medications ?? []
  const allergies = raw.allergies ?? []

  return {
    id: raw.patient_id,
    name,
    age: Number(raw.age ?? 0),
    sex: raw.sex || 'Not recorded',
    initials:
      name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() ?? '')
        .join('') || 'PT',
    condition: conditions[0] || 'Clinical review',
    conditions,
    medications,
    allergies,
    lastSeen: raw.admission_status || 'Active admission',
    assignedDoctorId: raw.assigned_doctor_id,
    assignedDoctorName: raw.assigned_doctor_name,
    department: raw.department,
    specialty: raw.specialty,
    roomBed: raw.room_bed,
    admissionStatus: raw.admission_status,
  }
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const token = getStoredToken()
  const headers = new Headers(init?.headers)

  if (!headers.has('Content-Type') && !(init?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
    })
  } catch {
    throw new Error(
      `Cannot reach MedPerplexity API at ${API_BASE}. ` +
      'Please verify FastAPI backend is running.',
    )
  }

  if (!response.ok) {
    let detail = ''
    try {
      const body = (await response.json()) as { detail?: string }
      detail = body.detail ? ` ${body.detail}` : ''
    } catch {
      // Non-JSON response
    }

    if (response.status === 401) {
      // Token expired or invalid
      setStoredToken(null)
      throw new Error(`Authentication required or session expired.${detail}`)
    }

    throw new Error(
      detail.trim() || `MedPerplexity API returned HTTP ${response.status}`,
    )
  }

  return response.json() as Promise<T>
}

// --------------------------------------------------------------------------- //
// Health Check
// --------------------------------------------------------------------------- //
export async function checkApiHealth(): Promise<boolean> {
  try {
    const result = await requestJson<{ status?: string }>('/api/health')
    return result.status === 'ok'
  } catch {
    return false
  }
}

// --------------------------------------------------------------------------- //
// Authentication & Hospital Session
// --------------------------------------------------------------------------- //
export async function login(email: string, password: string): Promise<HospitalUser> {
  const data = await requestJson<{
    token: string
    user: HospitalUser
  }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })

  setStoredToken(data.token)
  return data.user
}

export async function fetchCurrentUser(): Promise<HospitalUser | null> {
  const token = getStoredToken()
  if (!token) return null

  try {
    const data = await requestJson<{ user: HospitalUser }>('/api/auth/me')
    return data.user
  } catch {
    setStoredToken(null)
    return null
  }
}

export async function logout(): Promise<void> {
  try {
    await requestJson('/api/auth/logout', { method: 'POST' })
  } catch {
    // Ignore network error on logout
  } finally {
    setStoredToken(null)
  }
}

export async function updateUserPreferences(prefs: {
  specialty?: string
  secondary_specialties?: string[]
  preferred_date_range?: string
  theme?: string
}): Promise<void> {
  await requestJson('/api/auth/preferences', {
    method: 'PATCH',
    body: JSON.stringify(prefs),
  })
}

// --------------------------------------------------------------------------- //
// Patients & Clinical Workspace
// --------------------------------------------------------------------------- //
export async function fetchPatients(filters?: {
  doctor_id?: string
  department?: string
}): Promise<Patient[]> {
  const params = new URLSearchParams()
  if (filters?.doctor_id) params.set('doctor_id', filters.doctor_id)
  if (filters?.department) params.set('department', filters.department)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const payload = await requestJson<{ items?: ApiPatient[] }>(`/api/patients${qs}`)
  return (payload.items ?? []).map(mapPatient)
}

export async function fetchPatient(patientId: string): Promise<Patient> {
  const payload = await requestJson<ApiPatient>(
    `/api/patients/${encodeURIComponent(patientId)}`,
  )
  return mapPatient(payload)
}

export async function submitClinicalQuery(
  patientId: string,
  question: string,
  conversationId: string,
): Promise<{ response: ClinicalResponse; assessment_id: string }> {
  const payload = await requestJson<{
    patient_id: string
    response: ClinicalResponse
    assessment_id: string
  }>(`/api/patients/${encodeURIComponent(patientId)}/chat`, {
    method: 'POST',
    body: JSON.stringify({
      message: question,
      thread_id: conversationId,
    }),
  })

  if (!payload.response || typeof payload.response !== 'object') {
    throw new Error('The API did not return a valid clinical response object.')
  }

  return {
    response: payload.response,
    assessment_id: payload.assessment_id,
  }
}

export async function resetConversation(
  patientId: string,
  conversationId: string,
): Promise<void> {
  await requestJson(
    `/api/patients/${encodeURIComponent(patientId)}/chat/reset`,
    {
      method: 'POST',
      body: JSON.stringify({
        message: 'Reset conversation',
        thread_id: conversationId,
      }),
    },
  )
}

// --------------------------------------------------------------------------- //
// Independent Research Library
// --------------------------------------------------------------------------- //
export async function searchResearch(params: {
  query?: string
  specialty?: string
  publication_type?: string
  min_year?: number
  limit?: number
}): Promise<{
  papers: ResearchPaper[]
  count: number
  source: string
  error_note?: string | null
}> {
  const queryParts: string[] = []
  if (params.query) queryParts.push(`query=${encodeURIComponent(params.query)}`)
  if (params.specialty && params.specialty !== 'All Specialties') {
    queryParts.push(`specialty=${encodeURIComponent(params.specialty)}`)
  }
  if (params.publication_type && params.publication_type !== 'All Types') {
    queryParts.push(`publication_type=${encodeURIComponent(params.publication_type)}`)
  }
  if (params.min_year) queryParts.push(`min_year=${params.min_year}`)
  if (params.limit) queryParts.push(`limit=${params.limit}`)

  const qs = queryParts.length ? `?${queryParts.join('&')}` : ''
  return requestJson<{
    papers: ResearchPaper[]
    count: number
    source: string
    error_note?: string | null
  }>(`/api/research${qs}`)
}

export async function fetchSavedPapers(specialty?: string): Promise<SavedPaper[]> {
  const qs = specialty && specialty !== 'All Specialties'
    ? `?specialty=${encodeURIComponent(specialty)}`
    : ''
  const payload = await requestJson<{ items: SavedPaper[] }>(`/api/research/saved${qs}`)
  return payload.items ?? []
}

export async function saveResearchPaper(paper: Partial<ResearchPaper> & { pmid: string; title: string }, notes?: string): Promise<void> {
  await requestJson('/api/research/saved', {
    method: 'POST',
    body: JSON.stringify({
      pmid: paper.pmid,
      title: paper.title,
      authors: paper.authors || '',
      journal: paper.journal || '',
      pub_date: paper.pub_date || '',
      abstract: paper.abstract || '',
      doi: paper.doi || '',
      url: paper.url || `https://pubmed.ncbi.nlm.nih.gov/${paper.pmid}/`,
      evidence_type: paper.evidence_type || 'journal_article',
      specialty: paper.specialty || 'General Medicine',
      notes: notes || '',
    }),
  })
}

export async function removeSavedPaper(pmid: string): Promise<void> {
  await requestJson(`/api/research/saved/${encodeURIComponent(pmid)}`, {
    method: 'DELETE',
  })
}

export async function fetchPaperDetail(pmid: string): Promise<ResearchPaper> {
  return requestJson<ResearchPaper>(`/api/research/${encodeURIComponent(pmid)}`)
}

// --------------------------------------------------------------------------- //
// Clinical Assessments History & Audit
// --------------------------------------------------------------------------- //
export async function fetchAssessments(params?: {
  patient_id?: string
  status_filter?: string
  limit?: number
}): Promise<AssessmentHistoryItem[]> {
  const parts: string[] = []
  if (params?.patient_id) parts.push(`patient_id=${encodeURIComponent(params.patient_id)}`)
  if (params?.status_filter && params.status_filter !== 'all') {
    parts.push(`status_filter=${encodeURIComponent(params.status_filter)}`)
  }
  if (params?.limit) parts.push(`limit=${params.limit}`)

  const qs = parts.length ? `?${parts.join('&')}` : ''
  const data = await requestJson<{ items: AssessmentHistoryItem[] }>(`/api/assessments${qs}`)
  return data.items ?? []
}

export async function fetchAuditTrail(params?: {
  event_type?: string
  limit?: number
}): Promise<AuditEventItem[]> {
  const parts: string[] = []
  if (params?.event_type) parts.push(`event_type=${encodeURIComponent(params.event_type)}`)
  if (params?.limit) parts.push(`limit=${params.limit}`)

  const qs = parts.length ? `?${parts.join('&')}` : ''
  const data = await requestJson<{ items: AuditEventItem[] }>(`/api/audit${qs}`)
  return data.items ?? []
}

// --------------------------------------------------------------------------- //
// Medication Catalog
// --------------------------------------------------------------------------- //
export async function searchMedications(query: string, limit = 10): Promise<MedicationCatalogItem[]> {
  const data = await requestJson<{ items: MedicationCatalogItem[] }>(
    `/api/medications/search?q=${encodeURIComponent(query)}&limit=${limit}`,
  )
  return data.items ?? []
}

// --------------------------------------------------------------------------- //
// Hospital Administration (Role: hospital_admin)
// --------------------------------------------------------------------------- //
export async function fetchOrganizationInfo(): Promise<{
  id: string
  name: string
  code: string
  tier: string
  status: string
  entitlements: Record<string, unknown>
  stats: { active_seats: number; total_assessments: number }
  created_at: string
}> {
  return requestJson('/api/admin/organization')
}

export async function fetchHospitalUsers(): Promise<Array<{
  id: string
  email: string
  full_name: string
  designation: string
  department: string
  role: string
  status: string
  avatar_initials: string
  created_at: string
  specialty?: string
}>> {
  const data = await requestJson<{ items: Array<any> }>('/api/admin/users')
  return data.items ?? []
}

export async function createHospitalUser(user: {
  email: string
  password: string
  full_name: string
  designation: string
  department: string
  role: 'doctor' | 'hospital_admin'
  specialty?: string
}): Promise<void> {
  await requestJson('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify(user),
  })
}

export async function toggleHospitalUserStatus(userId: string, newStatus: 'active' | 'suspended'): Promise<void> {
  await requestJson(`/api/admin/users/${encodeURIComponent(userId)}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status: newStatus }),
  })
}

export function getApiBase(): string {
  return API_BASE
}
