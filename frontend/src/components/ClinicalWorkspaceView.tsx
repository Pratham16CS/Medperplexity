import { useEffect, useState } from 'react'
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileSearch,
  FlaskConical,
  History,
  Info,
  LoaderCircle,
  Pill,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Users
} from 'lucide-react'
import type {
  ClinicalResponse,
  HospitalUser,
  Patient
} from '../types/clinical'
import { resetConversation, submitClinicalQuery } from '../lib/api'

interface ClinicalWorkspaceViewProps {
  user: HospitalUser
  patients: Patient[]
  activePatientId?: string
  onSelectPatient?: (id: string) => void
  patientsLoading?: boolean
  patientsError?: string
  onRefreshPatients?: () => void
}

type Turn = {
  id: string
  query: string
  response: ClinicalResponse
  timestamp: string
}

function getPatientStarterPrompts(patient: Patient | null) {
  if (!patient) {
    return [
      {
        title: 'Patient Record Summary',
        prompt: "Summarize this patient's recorded medical conditions, allergies, and current medications using only the patient record. Clearly distinguish documented facts from missing information. Do not invent any details.",
        icon: FileSearch,
      },
      {
        title: 'Prescription Safety Check',
        prompt: 'Can I prescribe Amoxicillin 500mg TDS for this patient?',
        icon: ShieldAlert,
      },
      {
        title: 'Drug Interaction Review',
        prompt: 'Can I prescribe Potassium chloride supplement alongside the patient’s medications?',
        icon: FlaskConical,
      },
      {
        title: 'Jan Aushadhi Generic Savings',
        prompt: 'Find Jan Aushadhi generic alternatives and price comparison for Metformin 500mg',
        icon: Pill,
      },
      {
        title: 'Guideline Medical Literature',
        prompt: 'Retrieve recent high-evidence clinical guidelines and meta-analyses for hypertension.',
        icon: BookOpen,
      },
    ]
  }

  const prompts: Array<{ title: string; prompt: string; icon: any }> = []

  // 0. Grounded patient record summary
  prompts.push({
    title: `Record Summary: ${patient.name}`,
    prompt: `Summarize this patient's recorded medical conditions, allergies, and current medications using only the patient record. Clearly distinguish documented facts from missing information. Do not invent any details.`,
    icon: FileSearch,
  })

  // 1. Allergy safety check tailored to documented allergies
  const allergies = (patient.allergies || []).map((a) => a.toLowerCase())
  if (allergies.some((a) => a.includes('penicillin'))) {
    prompts.push({
      title: 'Prescription Order: Amoxicillin (Penicillin Allergy)',
      prompt: `Can I prescribe Amoxicillin 500mg TDS for ${patient.name}?`,
      icon: ShieldAlert,
    })
  } else if (allergies.some((a) => a.includes('aspirin'))) {
    prompts.push({
      title: 'Prescription Order: Aspirin 75mg (Aspirin Allergy)',
      prompt: `Prescribe Aspirin 75mg daily for ${patient.name}`,
      icon: ShieldAlert,
    })
  } else if (allergies.some((a) => a.includes('omeprazole'))) {
    prompts.push({
      title: 'Prescription Order: Omeprazole (PPI Allergy)',
      prompt: `Can I prescribe Omeprazole 20mg for acid reflux for ${patient.name}?`,
      icon: ShieldAlert,
    })
  } else if (allergies.some((a) => a.includes('sulfonamide'))) {
    prompts.push({
      title: 'Prescription Order: Co-trimoxazole (Sulfa Allergy)',
      prompt: `Can I prescribe Co-trimoxazole for ${patient.name}?`,
      icon: ShieldAlert,
    })
  } else if (allergies.some((a) => a.includes('cetirizine'))) {
    prompts.push({
      title: 'Prescription Order: Cetirizine (Documented Allergy)',
      prompt: `Can I prescribe Cetirizine 10mg daily for ${patient.name}?`,
      icon: ShieldAlert,
    })
  } else {
    prompts.push({
      title: 'Prescription Order: Paracetamol 500mg',
      prompt: `Can I prescribe Paracetamol 500mg TDS for ${patient.name}?`,
      icon: ShieldCheck,
    })
  }

  // 2. Interaction check tailored to active regimen
  const meds = patient.medications || []
  const medsLower = meds.map((m) => m.toLowerCase())
  if (medsLower.some((m) => m.includes('telmisartan') || m.includes('ramipril') || m.includes('losartan'))) {
    prompts.push({
      title: 'Interaction Check: Potassium + RAAS Inhibitor',
      prompt: `Prescribe Potassium chloride supplement for ${patient.name}`,
      icon: FlaskConical,
    })
  } else if (medsLower.some((m) => m.includes('clopidogrel'))) {
    prompts.push({
      title: 'Interaction Check: Omeprazole + Clopidogrel (CYP2C19)',
      prompt: `Can I prescribe Omeprazole 20mg for acid reflux while taking Clopidogrel?`,
      icon: FlaskConical,
    })
  } else if (medsLower.some((m) => m.includes('warfarin'))) {
    prompts.push({
      title: 'Interaction Check: Ibuprofen + Warfarin (Bleeding)',
      prompt: `Can I prescribe Ibuprofen 400mg TDS for joint pain while on Warfarin?`,
      icon: FlaskConical,
    })
  } else if (medsLower.some((m) => m.includes('simvastatin'))) {
    prompts.push({
      title: 'Interaction Check: Clarithromycin + Simvastatin (CYP3A4)',
      prompt: `Can I prescribe Clarithromycin 500mg BD for infection while on Simvastatin?`,
      icon: FlaskConical,
    })
  } else if (medsLower.some((m) => m.includes('isotretinoin'))) {
    prompts.push({
      title: 'Interaction Check: Doxycycline + Isotretinoin',
      prompt: `Can I prescribe Doxycycline 100mg while taking Isotretinoin?`,
      icon: FlaskConical,
    })
  } else {
    prompts.push({
      title: 'Interaction Safety: Order Verification',
      prompt: `Evaluate potential interaction risks between ${meds[0] || 'current medications'} and a new prescription.`,
      icon: FlaskConical,
    })
  }

  // 3. Jan Aushadhi generic substitution check
  const firstMed = meds[0] || 'Metformin 500'
  const secondMed = meds[1]
  const targetMed = secondMed && (secondMed.includes('Telmisartan') || secondMed.includes('Atorvastatin')) ? secondMed : firstMed
  prompts.push({
    title: `Generic Savings: ${targetMed}`,
    prompt: `Find Jan Aushadhi generic alternatives and price comparison for ${targetMed}`,
    icon: Pill,
  })

  // 4. Clinical guideline literature
  const condition = patient.conditions[0] || patient.condition || 'cardiovascular disease'
  prompts.push({
    title: `Guidelines: ${condition}`,
    prompt: `What are recent high-evidence clinical guidelines and meta-analyses for managing ${condition}?`,
    icon: BookOpen,
  })

  return prompts
}

export const ClinicalWorkspaceView: React.FC<ClinicalWorkspaceViewProps> = ({
  user,
  patients,
  activePatientId: propPatientId,
  onSelectPatient,
  patientsLoading = false,
  patientsError = '',
  onRefreshPatients
}) => {
  const [scopeFilter, setScopeFilter] = useState<'my' | 'all'>(() => {
    return user.role === 'hospital_admin' ? 'all' : 'my'
  })
  const [departmentFilter, setDepartmentFilter] = useState<string>('all')
  const [patientSearch, setPatientSearch] = useState('')
  const [selectedPatientId, setSelectedPatientId] = useState<string>(() => {
    if (propPatientId) return propPatientId
    return patients[0]?.id ?? 'PAT-001'
  })
  const [queryText, setQueryText] = useState('')
  const [conversationId, setConversationId] = useState<string>(
    () => `conv-${Date.now().toString(36)}`
  )
  const [turns, setTurns] = useState<Turn[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expandedAbstract, setExpandedAbstract] = useState<string | null>(null)
  const [showAudit, setShowAudit] = useState(false)

  const myPatients = patients.filter(
    (p) =>
      p.assignedDoctorId === user.id ||
      p.department?.toLowerCase() === user.department?.toLowerCase() ||
      p.specialty?.toLowerCase() === user.specialty?.toLowerCase()
  )

  const displayedPatients = patients.filter((p) => {
    if (scopeFilter === 'my') {
      const isMine =
        p.assignedDoctorId === user.id ||
        p.department?.toLowerCase() === user.department?.toLowerCase() ||
        p.specialty?.toLowerCase() === user.specialty?.toLowerCase()
      if (!isMine) return false
    }
    if (departmentFilter !== 'all') {
      if (p.department?.toLowerCase() !== departmentFilter.toLowerCase()) return false
    }
    if (!patientSearch.trim()) return true
    const term = patientSearch.toLowerCase()
    return (
      p.name.toLowerCase().includes(term) ||
      p.id.toLowerCase().includes(term) ||
      (p.assignedDoctorName && p.assignedDoctorName.toLowerCase().includes(term)) ||
      (p.department && p.department.toLowerCase().includes(term)) ||
      (p.roomBed && p.roomBed.toLowerCase().includes(term)) ||
      p.conditions.some((c) => c.toLowerCase().includes(term))
    )
  })

  // Synchronize selected patient when patients or prop changes
  useEffect(() => {
    if (propPatientId) {
      setSelectedPatientId(propPatientId)
    } else if (patients.length > 0 && !patients.some((p) => p.id === selectedPatientId)) {
      setSelectedPatientId(patients[0].id)
    }
  }, [propPatientId, patients, selectedPatientId])

  const handleScopeChange = (scope: 'my' | 'all') => {
    setScopeFilter(scope)
    if (scope === 'my' && myPatients.length > 0) {
      if (!myPatients.some((p) => p.id === selectedPatientId)) {
        handlePatientChange(myPatients[0].id)
      }
    }
  }

  const activePatient =
    patients.find((p) => p.id === selectedPatientId) ||
    displayedPatients[0] ||
    patients[0] ||
    null

  const handlePatientChange = (id: string) => {
    setSelectedPatientId(id)
    if (onSelectPatient) onSelectPatient(id)
    setTurns([])
    setError('')
    setConversationId(`conv-${Date.now().toString(36)}`)
    setShowAudit(false)
  }

  const handleReset = async () => {
    if (!activePatient) return
    try {
      await resetConversation(activePatient.id, conversationId)
      setTurns([])
      setError('')
      setConversationId(`conv-${Date.now().toString(36)}`)
      setShowAudit(false)
    } catch (e: any) {
      setError(e?.message || 'Failed to reset session.')
    }
  }

  const handleSend = async (presetPrompt?: string) => {
    const text = (presetPrompt || queryText).trim()
    if (!text || !activePatient || loading) return

    setQueryText('')
    setError('')
    setLoading(true)

    try {
      const { response } = await submitClinicalQuery(
        activePatient.id,
        text,
        conversationId
      )

      const newTurn: Turn = {
        id: `turn-${Date.now()}`,
        query: text,
        response,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }

      setTurns((prev) => [...prev, newTurn])
    } catch (err: any) {
      setError(err?.message || 'The clinical agent could not complete the request.')
    } finally {
      setLoading(false)
    }
  }

  const latestTurn = turns[turns.length - 1] || null
  const latestResponse = latestTurn?.response || null

  return (
    <div className="page-container">
      {patientsError && (
        <div
          style={{
            padding: 12,
            borderRadius: 'var(--radius-md)',
            background: 'var(--status-caution-bg)',
            color: 'var(--status-caution)',
            fontSize: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 16,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertCircle size={16} style={{ flexShrink: 0 }} />
            <span>{patientsError}</span>
          </div>
          {onRefreshPatients && (
            <button className="btn btn-secondary btn-sm" onClick={onRefreshPatients}>
              <RefreshCw size={12} /> Reconnect
            </button>
          )}
        </div>
      )}

      {/* Top Patient Context Banner */}
      {activePatient && (
        <div className="patient-banner">
          <div className="patient-banner-left">
            <div className="patient-initials" style={{ width: 44, height: 44, fontSize: 14 }}>
              {activePatient.initials}
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <h2 style={{ fontSize: 17, fontWeight: 800 }}>{activePatient.name}</h2>
                <span className="tag-chip">{activePatient.id}</span>
                <span className="tag-chip" style={{ background: 'var(--teal-soft)', color: 'var(--teal-primary)', fontWeight: 600 }}>
                  {activePatient.department || 'General Medicine'}
                </span>
                {activePatient.admissionStatus && (
                  <span className="tag-chip" style={{ fontSize: 11, background: 'var(--surface-hover)' }}>
                    {activePatient.admissionStatus}
                  </span>
                )}
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {activePatient.age} yrs · {activePatient.sex}
                </span>
              </div>
              <div className="patient-banner-meta" style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <div style={{ color: 'var(--teal-primary)', fontWeight: 600 }}>
                  Attending: <span>{activePatient.assignedDoctorName || user.full_name}</span>
                </div>
                {activePatient.roomBed && (
                  <>
                    <div>·</div>
                    <div style={{ color: 'var(--text-secondary)' }}>
                      Location: <strong>{activePatient.roomBed}</strong>
                    </div>
                  </>
                )}
                <div>·</div>
                <div>
                  <strong>Conditions:</strong>{' '}
                  {activePatient.conditions.join(', ') || 'None recorded'}
                </div>
                <div>·</div>
                <div>
                  <strong>Allergies:</strong>{' '}
                  {activePatient.allergies.length > 0 ? (
                    <span className="tag-chip tag-chip-danger">
                      <ShieldAlert size={12} style={{ display: 'inline', marginRight: 4 }} />
                      {activePatient.allergies.join(', ')}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>No documented allergies</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button className="btn btn-secondary btn-sm" onClick={handleReset} title="Clear conversation memory">
              <RefreshCw size={13} /> Reset Thread
            </button>
          </div>
        </div>
      )}

      {/* Main 3-Column Split */}
      <div className="clinical-grid">
        {/* Left Column: Patient Directory */}
        <div className="card patient-selector-card">
          <div className="card-title" style={{ justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Users size={16} color="var(--teal-primary)" />
              <span>Hospital Patients</span>
            </div>
            <span className="tag-chip">
              {displayedPatients.length} of {patients.length}
            </span>
          </div>

          {/* Doctor vs All Scope Selector */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 10 }}>
            <button
              type="button"
              className={`btn btn-sm ${scopeFilter === 'my' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ fontSize: 11, padding: '5px 8px', justifyContent: 'center' }}
              onClick={() => handleScopeChange('my')}
              title={`Show patients assigned to ${user.full_name} (${user.department})`}
            >
              My Patients ({myPatients.length})
            </button>
            <button
              type="button"
              className={`btn btn-sm ${scopeFilter === 'all' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ fontSize: 11, padding: '5px 8px', justifyContent: 'center' }}
              onClick={() => handleScopeChange('all')}
              title="Show all hospital inpatient and outpatient records"
            >
              All Hospital ({patients.length})
            </button>
          </div>

          {/* Department Filter Pills */}
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
            {['all', 'Cardiology', 'Neurology', 'Internal Medicine'].map((dept) => (
              <button
                key={dept}
                type="button"
                onClick={() => setDepartmentFilter(dept)}
                className="tag-chip"
                style={{
                  cursor: 'pointer',
                  fontSize: 10,
                  padding: '2px 8px',
                  background: departmentFilter === dept ? 'var(--teal-primary)' : 'var(--surface-hover)',
                  color: departmentFilter === dept ? '#fff' : 'var(--text-secondary)',
                  border: 'none',
                }}
              >
                {dept === 'all' ? 'All Depts' : dept}
              </button>
            ))}
          </div>

          <div className="search-input-wrap">
            <Search size={14} />
            <input
              type="text"
              placeholder="Find patient, condition, room…"
              className="search-input"
              value={patientSearch}
              onChange={(e) => setPatientSearch(e.target.value)}
            />
          </div>

          <div className="patient-scroll-list">
            {patientsLoading ? (
              <div style={{ textAlign: 'center', padding: '24px 10px', color: 'var(--text-muted)', fontSize: 12 }}>
                <LoaderCircle size={20} className="animate-spin" style={{ margin: '0 auto 8px' }} />
                <div>Loading hospital patient records…</div>
              </div>
            ) : displayedPatients.length > 0 ? (
              displayedPatients.map((p) => {
                const isSelected = p.id === selectedPatientId
                return (
                  <button
                    key={p.id}
                    className={`patient-item-btn ${isSelected ? 'selected' : ''}`}
                    onClick={() => handlePatientChange(p.id)}
                  >
                    <div className="patient-initials">{p.initials}</div>
                    <div className="patient-name-block">
                      <div className="patient-name-line">
                        <span>{p.name}</span>
                        <span className="patient-id-tag">{p.id}</span>
                      </div>
                      <div className="patient-detail-line">
                        {p.conditions[0] || 'Clinical Review'} · {p.age}y {p.sex[0].toUpperCase()}
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span
                          className="tag-chip"
                          style={{
                            fontSize: 9,
                            padding: '1px 5px',
                            background: isSelected ? 'rgba(255,255,255,0.2)' : 'var(--teal-soft)',
                            color: isSelected ? '#fff' : 'var(--teal-primary)',
                            fontWeight: 600,
                          }}
                        >
                          {p.department || 'Medicine'}
                        </span>
                        {p.roomBed && (
                          <span style={{ fontSize: 10, color: isSelected ? 'rgba(255,255,255,0.8)' : 'var(--text-muted)' }}>
                            {p.roomBed}
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                )
              })
            ) : (
              <div style={{ textAlign: 'center', padding: '20px 10px', color: 'var(--text-muted)', fontSize: 12 }}>
                <div>No patient records match the current filter.</div>
                <div style={{ marginTop: 8, display: 'flex', gap: 6, justifyContent: 'center' }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    style={{ fontSize: 11 }}
                    onClick={() => {
                      setScopeFilter('all')
                      setDepartmentFilter('all')
                      setPatientSearch('')
                    }}
                  >
                    View All {patients.length} Patients
                  </button>
                  {onRefreshPatients && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: 11 }}
                      onClick={onRefreshPatients}
                    >
                      <RefreshCw size={11} /> Refresh
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Center Column: Query Composer & History */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card query-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div className="card-title">
                <Sparkles size={16} color="var(--teal-primary)" />
                <span>Clinical Decision Query</span>
              </div>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Session {conversationId}
              </span>
            </div>

            <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              Submit a prescription check, allergy verification, or literature review for{' '}
              <strong>{activePatient?.name || 'the selected patient'}</strong>.
            </p>

            <div className="starter-chips">
              {getPatientStarterPrompts(activePatient).map((starter) => (
                <button
                  key={starter.title}
                  className="starter-chip"
                  onClick={() => handleSend(starter.prompt)}
                  disabled={loading}
                  title={starter.prompt}
                >
                  <starter.icon size={13} style={{ display: 'inline', marginRight: 4 }} />
                  {starter.title}
                </button>
              ))}
            </div>

            <div className="composer-box">
              <textarea
                className="composer-textarea"
                placeholder="Ask a clinical question (e.g., 'Prescribe Potassium chloride supplement' or 'Can I give Clopidogrel with Omeprazole?')…"
                value={queryText}
                onChange={(e) => setQueryText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void handleSend()
                  }
                }}
              />

              <div className="composer-bottom">
                <span className="composer-hint">Shift + Enter for new line</span>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={!queryText.trim() || loading}
                  onClick={() => void handleSend()}
                >
                  {loading ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}
                  <span>{loading ? 'Evaluating…' : 'Run Check'}</span>
                </button>
              </div>
            </div>

            {error && (
              <div
                style={{
                  padding: 10,
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--status-blocked-bg)',
                  color: 'var(--status-blocked)',
                  fontSize: 12,
                  display: 'flex',
                  gap: 8,
                  alignItems: 'center',
                }}
              >
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}
          </div>

          {/* Conversation History Turns */}
          {turns.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {turns.map((turn, index) => (
                <div key={turn.id} className="card" style={{ padding: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                    <span>TURN {index + 1} · {turn.timestamp}</span>
                    <span className={`status-pill status-${turn.response.status}`} style={{ fontSize: 10, padding: '2px 8px' }}>
                      {turn.response.status.toUpperCase()}
                    </span>
                  </div>

                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
                    Q: {turn.query}
                  </div>

                  <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    {turn.response.message}
                  </p>
                </div>
              ))}
            </div>
          )}

          {turns.length === 0 && !loading && (
            <div className="card" style={{ textAlign: 'center', padding: '36px 20px', color: 'var(--text-muted)' }}>
              <ShieldCheck size={36} color="var(--teal-primary)" style={{ margin: '0 auto 12px', opacity: 0.8 }} />
              <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
                Clinical Decision Support Ready
              </h3>
              <p style={{ fontSize: 13, maxWidth: 420, margin: '0 auto', lineHeight: 1.5 }}>
                Submit a prescription order or click a starter check above. MedPerplexity will evaluate
                patient safety constraints, search PubMed literature, and assess claim provenance.
              </p>
            </div>
          )}
        </div>

        {/* Right Column: Structured Evidence, Safety & Audit Breakdown */}
        <div className="clinical-right-col" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {latestResponse ? (
            <div className="result-display">
              {/* System Assessment Status Card */}
              <div className={`card status-hero-card ${latestResponse.status}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <span className={`status-pill status-${latestResponse.status}`}>
                    {latestResponse.status === 'blocked' ? (
                      <ShieldAlert size={14} />
                    ) : latestResponse.status === 'caution' ? (
                      <AlertCircle size={14} />
                    ) : (
                      <CheckCircle2 size={14} />
                    )}
                    {latestResponse.status.toUpperCase()}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    Evidence: {latestResponse.evidence_level || 'standard'}
                  </span>
                </div>

                <h3 style={{ fontSize: 15, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.3 }}>
                  {latestResponse.title}
                </h3>

                <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.5 }}>
                  {latestResponse.message}
                </p>

                {latestResponse.suggestion && (
                  <div style={{ marginTop: 12, padding: 10, background: 'var(--surface-soft)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', fontSize: 12 }}>
                    <strong>Clinician Suggestion:</strong> {latestResponse.suggestion}
                  </div>
                )}
              </div>

              {/* Safety Flags Section */}
              {latestResponse.flags && latestResponse.flags.length > 0 && (
                <div className="card">
                  <div className="card-title">
                    <ShieldAlert size={16} color="var(--status-blocked)" />
                    <span>Safety Flags ({latestResponse.flags.length})</span>
                  </div>

                  {latestResponse.flags.map((flag, i) => (
                    <div key={i} className={`safety-flag-item ${flag.severity}`}>
                      <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                      <div>
                        <strong>{flag.type?.toUpperCase() || 'ALERT'}:</strong> {flag.detail}
                        {flag.drug && <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2 }}>Medicine: {flag.drug}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Claim Support Validation Card */}
              <div className="card">
                <div className="card-title">
                  <CheckCircle2 size={16} color="var(--teal-primary)" />
                  <span>Claim-Support Validation</span>
                </div>

                <div className="claim-score-row">
                  <div
                    className={`claim-score-orb ${latestResponse.claim_support?.status || 'not_assessed'}`}
                  >
                    {latestResponse.claim_support?.supported ?? 0}/{latestResponse.claim_support?.total ?? 0}
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>
                      {latestResponse.claim_support?.status === 'supported'
                        ? 'Abstract Provenance Verified'
                        : latestResponse.claim_support?.status === 'insufficient'
                        ? 'Insufficient Abstract Support'
                        : 'Not Formally Assessed'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      Quotes matched against retrieved publication text.
                    </div>
                  </div>
                </div>

                {latestResponse.claim_support?.checks && latestResponse.claim_support.checks.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
                    {latestResponse.claim_support.checks.map((c, idx) => (
                      <div key={idx} style={{ fontSize: 11, padding: 8, background: 'var(--surface-soft)', borderRadius: 6, border: '1px solid var(--border)' }}>
                        <div style={{ fontWeight: 600, color: c.passed ? 'var(--status-approved)' : 'var(--status-blocked)' }}>
                          {c.passed ? '✓ Supported' : '✕ Unsupported'}: PMID {c.pmid}
                        </div>
                        <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>{c.claim}</div>
                      </div>
                    ))}
                  </div>
                )}

                <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10, lineHeight: 1.4 }}>
                  <Info size={12} style={{ display: 'inline', marginRight: 4 }} />
                  Source-quote verification checks textual provenance, not independent pharmacological truth.
                </p>
              </div>

              {/* Jan Aushadhi Generic Savings Card */}
              {latestResponse.savings?.found && (
                <div className="card">
                  <div className="card-title">
                    <Pill size={16} color="var(--teal-primary)" />
                    <span>Jan Aushadhi Generic Discovery</span>
                  </div>

                  <div className="savings-banner" style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                      Price Comparison
                    </div>
                    <div style={{ fontSize: 13, marginTop: 4 }}>
                      {latestResponse.savings.text}
                    </div>
                  </div>

                  {latestResponse.savings.items && latestResponse.savings.items.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
                      {latestResponse.savings.items.map((item, idx) => (
                        <div key={idx} style={{ padding: 10, background: 'var(--surface-soft)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', fontSize: 12 }}>
                          <strong>{item.generic_name}</strong>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, color: 'var(--text-secondary)', fontSize: 11 }}>
                            <span>Jan Aushadhi: ₹{item.jan_aushadhi_price?.toFixed(2)} ({item.unit_size})</span>
                            <span style={{ color: 'var(--status-approved)', fontWeight: 700 }}>
                              Save ₹{item.savings_amount?.toFixed(2)} ({item.savings_percent}%)
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Retrieved PubMed Evidence Sources */}
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div className="card-title">
                    <BookOpen size={16} color="var(--teal-primary)" />
                    <span>Retrieved PubMed Sources ({latestResponse.sources?.length ?? 0})</span>
                  </div>
                </div>

                {latestResponse.sources && latestResponse.sources.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
                    {latestResponse.sources.map((src) => {
                      const isExpanded = expandedAbstract === src.pmid
                      return (
                        <div key={src.pmid} className="source-paper-card">
                          <div className="source-paper-title">{src.title}</div>
                          <div className="source-paper-meta">
                            <span>PMID {src.pmid}</span>
                            <span>{src.journal}</span>
                            <span>{src.pub_date}</span>
                          </div>

                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
                            <a
                              href={src.url || `https://pubmed.ncbi.nlm.nih.gov/${src.pmid}/`}
                              target="_blank"
                              rel="noreferrer"
                              style={{ fontSize: 11, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 3 }}
                            >
                              Open in PubMed <ExternalLink size={11} />
                            </a>

                            {src.abstract && (
                              <button
                                style={{ fontSize: 11, color: 'var(--teal-primary)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 2 }}
                                onClick={() => setExpandedAbstract(isExpanded ? null : src.pmid)}
                              >
                                {isExpanded ? 'Hide Abstract' : 'View Abstract'}
                                {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                              </button>
                            )}
                          </div>

                          {isExpanded && src.abstract && (
                            <div className="abstract-box">
                              {src.abstract}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>
                    No PubMed citations returned for this turn.
                  </div>
                )}
              </div>

              {/* Audit Transparency Toggle */}
              <div className="card" style={{ padding: 14 }}>
                <button
                  style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center', fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}
                  onClick={() => setShowAudit(!showAudit)}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <History size={14} color="var(--teal-primary)" />
                    <span>Audit Details & Execution Trail</span>
                  </span>
                  {showAudit ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>

                {showAudit && latestResponse.audit && (
                  <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div><strong>Timestamp:</strong> {latestResponse.audit.timestamp || 'N/A'}</div>
                    <div><strong>Tools Dispatched:</strong> {JSON.stringify(latestResponse.audit.tools || {})}</div>
                    <div><strong>LLM Steps:</strong> {latestResponse.audit.llm?.length ?? 0} step(s)</div>
                    {latestResponse.audit.notes && (
                      <div style={{ marginTop: 4, padding: 8, background: 'var(--surface-soft)', borderRadius: 6 }}>
                        <strong>Audit Notes:</strong>
                        <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                          {latestResponse.audit.notes.map((n, i) => (
                            <li key={i}>{n}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="card" style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--text-muted)' }}>
              <FileSearch size={32} color="var(--text-muted)" style={{ margin: '0 auto 10px', opacity: 0.6 }} />
              <div style={{ fontSize: 13, fontWeight: 600 }}>Structured Clinical Output</div>
              <p style={{ fontSize: 11, marginTop: 4 }}>
                Status, PubMed sources, claim verification, and generic savings will appear here once you run a query.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
