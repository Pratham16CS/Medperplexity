import { useEffect, useState } from 'react'
import {
  LoaderCircle,
  Search,
  ShieldCheck,
} from 'lucide-react'
import type { AuditEventItem, HospitalUser } from '../types/clinical'
import { fetchAuditTrail } from '../lib/api'

interface AuditViewProps {
  user: HospitalUser
}

export const AuditView: React.FC<AuditViewProps> = ({ user }) => {
  const [events, setEvents] = useState<AuditEventItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  useEffect(() => {
    fetchAuditTrail({ limit: 40 })
      .then(setEvents)
      .finally(() => setLoading(false))
  }, [])

  const filtered = events.filter((ev) => {
    const term = search.toLowerCase()
    return (
      ev.event_type.toLowerCase().includes(term) ||
      (ev.user_name || '').toLowerCase().includes(term) ||
      (ev.resource_type || '').toLowerCase().includes(term) ||
      (ev.resource_id || '').toLowerCase().includes(term)
    )
  })

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-title-block">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, color: 'var(--teal-primary)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4 }}>
            <ShieldCheck size={14} /> Security & Governance
          </div>
          <h1>Hospital Audit Log</h1>
          <p>
            Immutable event logging for clinical decision support queries, research activity, and administrative actions.
          </p>
        </div>
      </div>

      <div className="card" style={{ padding: '14px 20px', marginBottom: 20 }}>
        <div className="search-input-wrap">
          <Search size={15} />
          <input
            type="text"
            className="search-input"
            placeholder="Search audit trail by event type, clinician, or resource ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 50, color: 'var(--text-muted)' }}>
          <LoaderCircle size={24} className="animate-spin" style={{ margin: '0 auto 10px' }} />
          <div>Retrieving audit trail…</div>
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Event Type</th>
                <th>Clinician / User</th>
                <th>Resource</th>
                <th>Event Details</th>
                <th>Timestamp (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((ev) => (
                <tr key={ev.id}>
                  <td>
                    <span className="tag-chip" style={{ fontWeight: 700, textTransform: 'uppercase' }}>
                      {ev.event_type.replace('_', ' ')}
                    </span>
                  </td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{ev.user_name || user.full_name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{ev.user_email || user.email}</div>
                  </td>
                  <td>
                    <span className="tag-chip">
                      {ev.resource_type}: {ev.resource_id || 'system'}
                    </span>
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-secondary)', maxWidth: 360 }}>
                    {JSON.stringify(ev.details)}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {ev.timestamp.replace('T', ' ').replace('Z', '')}
                  </td>
                </tr>
              ))}

              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: 32, color: 'var(--text-muted)' }}>
                    No audit records match your search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
