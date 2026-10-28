import { useEffect, useState } from 'react'
import {
  Building,
  CheckCircle2,
  Hospital,
  LoaderCircle,
  ShieldCheck,
  UserPlus,
  Users,
  X
} from 'lucide-react'
import type { HospitalUser } from '../types/clinical'
import {
  createHospitalUser,
  fetchHospitalUsers,
  fetchOrganizationInfo,
  toggleHospitalUserStatus
} from '../lib/api'

interface HospitalAdminViewProps {
  user: HospitalUser
}

export const HospitalAdminView: React.FC<HospitalAdminViewProps> = ({ user }) => {
  const [orgInfo, setOrgInfo] = useState<any>(null)
  const [staffUsers, setStaffUsers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [actionError, setActionError] = useState('')

  // Form state
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [designation, setDesignation] = useState('')
  const [department, setDepartment] = useState('')
  const [role, setRole] = useState<'doctor' | 'hospital_admin'>('doctor')
  const [specialty, setSpecialty] = useState('Cardiology')
  const [submitting, setSubmitting] = useState(false)

  const loadData = async () => {
    setLoading(true)
    try {
      const [org, usersList] = await Promise.all([
        fetchOrganizationInfo(),
        fetchHospitalUsers(),
      ])
      setOrgInfo(org)
      setStaffUsers(usersList)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const handleToggleStatus = async (userId: string, currentStatus: string) => {
    const nextStatus = currentStatus === 'active' ? 'suspended' : 'active'
    setActionError('')
    try {
      await toggleHospitalUserStatus(userId, nextStatus)
      await loadData()
    } catch (e: any) {
      setActionError(e?.message || 'Failed to update user status.')
    }
  }

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()
    setActionError('')
    setSubmitting(true)
    try {
      await createHospitalUser({
        full_name: fullName,
        email,
        password,
        designation,
        department,
        role,
        specialty,
      })
      setShowAddModal(false)
      setFullName('')
      setEmail('')
      setPassword('')
      setDesignation('')
      setDepartment('')
      await loadData()
    } catch (err: any) {
      setActionError(err?.message || 'Failed to create user.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="page-container" style={{ textAlign: 'center', padding: 80 }}>
        <LoaderCircle size={28} className="animate-spin" style={{ margin: '0 auto 12px' }} />
        <div>Loading hospital organization management…</div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-title-block">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, color: 'var(--teal-primary)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4 }}>
            <Building size={14} /> Hospital Administration
          </div>
          <h1>{orgInfo?.name || 'Hospital Administration'}</h1>
          <p>
            Manage hospital clinicians, configure specialty entitlements, and monitor platform utilization.
          </p>
        </div>

        <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
          <UserPlus size={16} /> Provision Clinician
        </button>
      </div>

      {actionError && (
        <div style={{ padding: 12, background: 'var(--status-blocked-bg)', color: 'var(--status-blocked)', borderRadius: 'var(--radius-md)', marginBottom: 20, fontSize: 12 }}>
          {actionError}
        </div>
      )}

      {/* Organization Entitlements & Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 24 }}>
        <div className="card">
          <div className="card-title">
            <Hospital size={16} color="var(--teal-primary)" />
            <span>Hospital Package & Licensing</span>
          </div>

          <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>License Tier:</span>
              <strong>{orgInfo?.tier || 'Hospital Enterprise'}</strong>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Organization Code:</span>
              <span className="tag-chip">{orgInfo?.code}</span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Active Clinician Seats:</span>
              <strong>{orgInfo?.stats?.active_seats} Provisioned</strong>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Total Clinical Assessments:</span>
              <strong>{orgInfo?.stats?.total_assessments} Completed</strong>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-title">
            <ShieldCheck size={16} color="var(--teal-primary)" />
            <span>Licensed Entitlements</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 14 }}>
            {orgInfo?.entitlements &&
              Object.entries(orgInfo.entitlements).map(([key, _val]) => (
                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <CheckCircle2 size={14} color="var(--status-approved)" />
                  <span style={{ textTransform: 'capitalize' }}>
                    {key.replace(/_/g, ' ')}
                  </span>
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* Staff Directory Table */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">
            <Users size={16} color="var(--teal-primary)" />
            <span>Hospital Staff Directory ({staffUsers.length})</span>
          </div>
        </div>

        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Clinician / Staff</th>
                <th>Role</th>
                <th>Department</th>
                <th>Specialty</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {staffUsers.map((su) => (
                <tr key={su.id}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className="patient-initials" style={{ width: 32, height: 32, fontSize: 11 }}>
                        {su.avatar_initials}
                      </div>
                      <div>
                        <strong>{su.full_name}</strong>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{su.email}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="tag-chip" style={{ textTransform: 'capitalize' }}>
                      {su.role.replace('_', ' ')}
                    </span>
                  </td>
                  <td>{su.department}</td>
                  <td>{su.specialty || su.designation}</td>
                  <td>
                    <span className={`status-pill ${su.status === 'active' ? 'status-approved' : 'status-blocked'}`} style={{ fontSize: 10, padding: '2px 8px' }}>
                      {su.status.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {su.id !== user.id ? (
                      <button
                        className={`btn btn-sm ${su.status === 'active' ? 'btn-danger' : 'btn-secondary'}`}
                        onClick={() => handleToggleStatus(su.id, su.status)}
                      >
                        {su.status === 'active' ? 'Suspend' : 'Activate'}
                      </button>
                    ) : (
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Current User</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add User Modal */}
      {showAddModal && (
        <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Provision Hospital Account</h2>
              <button onClick={() => setShowAddModal(false)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateUser} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                  Full Name
                </label>
                <input
                  type="text"
                  required
                  className="search-input"
                  style={{ paddingLeft: 12 }}
                  placeholder="e.g. Dr. Kavita Deshmukh, MD"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                    Email
                  </label>
                  <input
                    type="email"
                    required
                    className="search-input"
                    style={{ paddingLeft: 12 }}
                    placeholder="doctor@metrohealth.org"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                    Initial Password
                  </label>
                  <input
                    type="password"
                    required
                    className="search-input"
                    style={{ paddingLeft: 12 }}
                    placeholder="Min 8 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                    Designation
                  </label>
                  <input
                    type="text"
                    required
                    className="search-input"
                    style={{ paddingLeft: 12 }}
                    placeholder="e.g. Consultant Cardiologist"
                    value={designation}
                    onChange={(e) => setDesignation(e.target.value)}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                    Department
                  </label>
                  <input
                    type="text"
                    required
                    className="search-input"
                    style={{ paddingLeft: 12 }}
                    placeholder="e.g. Cardiology"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                    Role
                  </label>
                  <select
                    className="search-input"
                    style={{ paddingLeft: 12 }}
                    value={role}
                    onChange={(e) => setRole(e.target.value as any)}
                  >
                    <option value="doctor">Doctor</option>
                    <option value="hospital_admin">Hospital Administrator</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                    Specialty Designation
                  </label>
                  <input
                    type="text"
                    className="search-input"
                    style={{ paddingLeft: 12 }}
                    placeholder="e.g. Cardiology"
                    value={specialty}
                    onChange={(e) => setSpecialty(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowAddModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submitting}
                >
                  {submitting ? 'Creating…' : 'Create Clinician Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
