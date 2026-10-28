export type SafetyStatus = 'approved' | 'caution' | 'blocked' | 'info'

export type Patient = {
  id: string
  name: string
  age: number
  sex: string
  initials: string
  condition: string
  conditions: string[]
  medications: string[]
  allergies: string[]
  lastSeen?: string
  assignedDoctorId?: string
  assignedDoctorName?: string
  department?: string
  specialty?: string
  roomBed?: string
  admissionStatus?: string
}

export type EvidenceSource = {
  pmid: string
  title: string
  journal?: string
  pub_date?: string
  evidence_type?: string
  url?: string
  abstract?: string
  authors?: string
  doi?: string
}

export type ClaimCheck = {
  claim: string
  pmid: string
  passed: boolean
  quote_valid: boolean
  verdict: string
  rationale?: string
}

export type ClaimSupport = {
  status: 'supported' | 'insufficient' | 'not_assessed'
  total: number
  supported: number
  issues?: string[]
  checks?: ClaimCheck[]
}

export type SavingsItem = {
  generic_name?: string
  jan_aushadhi_price?: number
  typical_brand_price?: number
  savings_amount?: number
  savings_percent?: number
  unit_size?: string
  confidence?: string
  ambiguous?: boolean
}

export type ClinicalResponse = {
  status: SafetyStatus
  title: string
  message: string
  suggestion?: string
  evidence?: string
  evidence_level?: string
  sources?: EvidenceSource[]
  pmids?: string[]
  flags?: Array<{ severity: string; detail: string; type?: string; drug?: string }>
  claim_support?: ClaimSupport
  savings?: { found?: boolean; text?: string; items?: SavingsItem[] }
  disclaimer?: string
  audit?: {
    notes?: string[]
    timestamp?: string
    tools?: Record<string, unknown>
    llm?: Array<Record<string, unknown>>
    patient_id?: string
  }
}

export type Organization = {
  id: string
  name: string
  code: string
  tier: string
  entitlements?: Record<string, boolean | number | string>
}

export type HospitalUser = {
  id: string
  email: string
  full_name: string
  designation: string
  department: string
  role: 'doctor' | 'hospital_admin' | 'platform_admin'
  avatar_initials: string
  specialty: string
  secondary_specialties?: string[]
  preferred_date_range?: string
  theme?: string
  organization: Organization
}

export type ResearchPaper = {
  pmid: string
  title: string
  authors: string
  journal: string
  pub_date: string
  publication_types?: string[]
  evidence_type?: string
  doi?: string
  abstract: string
  url: string
  specialty?: string
  is_saved?: boolean
}

export type SavedPaper = {
  id: string
  user_id: string
  organization_id: string
  pmid: string
  title: string
  authors: string
  journal: string
  pub_date: string
  abstract: string
  doi?: string
  url: string
  evidence_type: string
  specialty: string
  notes?: string
  saved_at: string
}

export type AssessmentHistoryItem = {
  id: string
  organization_id: string
  user_id: string
  patient_id: string
  thread_id: string
  query: string
  status: SafetyStatus
  title: string
  message: string
  structured_response: ClinicalResponse
  audit?: Record<string, unknown>
  created_at: string
}

export type AuditEventItem = {
  id: string
  organization_id: string
  user_id: string
  user_name?: string
  user_email?: string
  user_role?: string
  event_type: string
  resource_type: string
  resource_id?: string
  details: Record<string, unknown>
  timestamp: string
}

export type MedicationCatalogItem = {
  id: number
  generic_name: string
  jan_price?: number
  unit_size?: string
  market_avg_price?: number
  common_brands?: string[]
  savings_percentage?: number
  savings_alert?: string
  drug_code?: string
  group_name?: string
}
