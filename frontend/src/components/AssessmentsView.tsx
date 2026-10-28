import { useEffect, useState } from 'react'
import {
  AlertCircle,
  Eye,
  Filter,
  History,
  LoaderCircle,
  Search,
  X
} from 'lucide-react'
import type { AssessmentHistoryItem, HospitalUser } from '../types/clinical'
import { fetchAssessments } from '../lib/api'

interface AssessmentsViewProps {
  user: HospitalUser
  initialSelectedId?: string
}

export const AssessmentsView: React.FC<AssessmentsViewProps> = ({
  user: _user,
  initialSelectedId,
}) => {
  const [assessments, setAssessments] = useState<AssessmentHistoryItem[]>([])
  const [statusFilter, setStatusFilter] = useState('all')
  const [patientSearch, setPatientSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [selectedItem, setSelectedItem] = useState<AssessmentHistoryItem | null>(null)

  const loadAssessments = async () => {
    setLoading(true)
    try {
      const data = await fetchAssessments({
        status_filter: statusFilter,
        limit: 50,
      })
      setAssessments(data)
      if (initialSelectedId) {
        const found = data.find((a) => a.id === initialSelectedId)
        if (found) setSelectedItem(found)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAssessments()
  }, [statusFilter])

  const filtered = assessments.filter((a) => {
    const term = patientSearch.toLowerCase()
    return (
      a.patient_id.toLowerCase().includes(term) ||
      a.query.toLowerCase().includes(term) ||
      a.title.toLowerCase().includes(term)
    )
  })

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-title-block">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, color: 'var(--teal-primary)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4 }}>
            <History size={14} /> Hospital Audit Record
          </div>
          <h1>Clinical Assessment History</h1>
          <p>
            Persisted record of clinical evaluations, deterministic safety flags, and evidence retrievals.
          </p>
        </div>
      </div>

      {/* Filter Row */}
      <div className="card" style={{ padding: '14px 20px', marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="search-input-wrap" style={{ flex: '1 1 300px' }}>
            <Search size={15} />
            <input
              type="text"
              className="search-input"
              placeholder="Search by patient ID (e.g. PAT-001) or query text…"
              value={patientSearch}
              onChange={(e) => setPatientSearch(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Filter size={14} color="var(--text-muted)" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              style={{
                padding: '8px 12px',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border)',
                background: 'var(--surface-soft)',
                fontSize: 12,
              }}
            >
              <option value="all">All Statuses</option>
              <option value="blocked">Blocked</option>
              <option value="caution">Caution</option>
              <option value="approved">Approved</option>
              <option value="info">Info</option>
            </select>
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 50, color: 'var(--text-muted)' }}>
          <LoaderCircle size={24} className="animate-spin" style={{ margin: '0 auto 10px' }} />
          <div>Loading assessment history from SQLite database…</div>
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Patient</th>
                <th>Clinical Query</th>
                <th>Assessment Summary</th>
                <th>Timestamp</th>
                <th style={{ textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className={`status-pill status-${item.status}`} style={{ fontSize: 11, padding: '3px 8px' }}>
                      {item.status.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <strong className="tag-chip">{item.patient_id}</strong>
                  </td>
                  <td style={{ maxWidth: 260, fontWeight: 600 }}>
                    {item.query}
                  </td>
                  <td style={{ maxWidth: 300, color: 'var(--text-secondary)' }}>
                    {item.title}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {item.created_at.slice(0, 16).replace('T', ' ')}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => setSelectedItem(item)}
                    >
                      <Eye size={13} /> View Result
                    </button>
                  </td>
                </tr>
              ))}

              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: 32, color: 'var(--text-muted)' }}>
                    No assessment history records found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Inspection Modal */}
      {selectedItem && (
        <div className="modal-overlay" onClick={() => setSelectedItem(null)}>
          <div className="modal-dialog" style={{ maxWidth: 700 }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={`status-pill status-${selectedItem.status}`}>
                  {selectedItem.status.toUpperCase()}
                </span>
                <span className="tag-chip">{selectedItem.patient_id}</span>
              </div>
              <button onClick={() => setSelectedItem(null)}>
                <X size={18} />
              </button>
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Query Submitted
              </div>
              <h2 style={{ fontSize: 16, fontWeight: 800, color: 'var(--text-primary)', marginTop: 2 }}>
                {selectedItem.query}
              </h2>
            </div>

            <div style={{ padding: 14, background: 'var(--surface-soft)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
                {selectedItem.title}
              </div>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
                {selectedItem.message}
              </p>
            </div>

            {/* Safety Flags */}
            {selectedItem.structured_response?.flags && selectedItem.structured_response.flags.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
                  Triggered Safety Flags
                </div>
                {selectedItem.structured_response.flags.map((f, i) => (
                  <div key={i} className={`safety-flag-item ${f.severity}`} style={{ marginTop: 4 }}>
                    <AlertCircle size={15} />
                    <span><strong>{f.type?.toUpperCase()}:</strong> {f.detail}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Evidence Sources */}
            {selectedItem.structured_response?.sources && selectedItem.structured_response.sources.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
                  Retrieved PubMed Citations ({selectedItem.structured_response.sources.length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {selectedItem.structured_response.sources.map((s) => (
                    <div key={s.pmid} style={{ padding: 8, background: 'var(--surface-soft)', borderRadius: 6, border: '1px solid var(--border)', fontSize: 12 }}>
                      <strong>PMID {s.pmid}:</strong> {s.title} ({s.journal})
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ fontSize: 11, color: 'var(--text-muted)', paddingTop: 10, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
              <span>Recorded: {selectedItem.created_at}</span>
              <span>Session Thread: {selectedItem.thread_id}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
