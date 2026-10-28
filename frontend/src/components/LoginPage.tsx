import React, { useState } from 'react'
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Eye,
  EyeOff,
  LoaderCircle,
  Lock,
  Mail,
  UserCheck
} from 'lucide-react'
import { login } from '../lib/api'
import type { HospitalUser } from '../types/clinical'

interface LoginPageProps {
  onSuccess: (user: HospitalUser) => void
  onCancel: () => void
}

export const LoginPage: React.FC<LoginPageProps> = ({ onSuccess, onCancel }) => {
  const [email, setEmail] = useState('dr.sharma@metrohealth.org')
  const [password, setPassword] = useState('DoctorPassword123!')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const user = await login(email, password)
      onSuccess(user)
    } catch (err: any) {
      setError(err?.message || 'Failed to authenticate with hospital credentials.')
    } finally {
      setLoading(false)
    }
  }

  const selectDemoAccount = (accEmail: string, accPass: string) => {
    setEmail(accEmail)
    setPassword(accPass)
    setError('')
  }

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-dialog"
        style={{ maxWidth: 480, padding: 32 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div
            className="brand-icon"
            style={{ width: 48, height: 48, margin: '0 auto 12px', borderRadius: 14 }}
          >
            <Activity size={24} strokeWidth={2.5} />
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)' }}>
            Hospital Clinician Sign In
          </h2>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
            St. Jude Metropolitan Health System · Enterprise Access
          </p>
        </div>

        {error && (
          <div
            style={{
              padding: 12,
              borderRadius: 'var(--radius-md)',
              background: 'var(--status-blocked-bg)',
              color: 'var(--status-blocked)',
              fontSize: 12,
              display: 'flex',
              gap: 8,
              alignItems: 'center',
              marginBottom: 16
            }}
          >
            <AlertCircle size={16} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
              Hospital Email
            </label>
            <div className="search-input-wrap">
              <Mail size={16} />
              <input
                type="email"
                required
                className="search-input"
                style={{ paddingLeft: 38 }}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="doctor@metrohealth.org"
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
              Password
            </label>
            <div className="search-input-wrap" style={{ position: 'relative' }}>
              <Lock size={16} />
              <input
                type={showPassword ? 'text' : 'password'}
                required
                className="search-input"
                style={{ paddingLeft: 38, paddingRight: 38 }}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{ position: 'absolute', right: 10, color: 'var(--text-muted)', padding: 4 }}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', padding: '11px', marginTop: 6 }}
            disabled={loading}
          >
            {loading ? <LoaderCircle size={16} className="animate-spin" /> : <ArrowRight size={16} />}
            {loading ? 'Authenticating…' : 'Access Clinical Workspace'}
          </button>
        </form>

        {/* Quick Demo Credentials */}
        <div style={{ marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
            <UserCheck size={14} /> Quick Demo Profiles
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <button
              type="button"
              className="starter-chip"
              style={{ textAlign: 'left', padding: '8px 10px', height: 'auto' }}
              onClick={() => selectDemoAccount('dr.sharma@metrohealth.org', 'DoctorPassword123!')}
            >
              <strong style={{ display: 'block', color: 'var(--text-primary)', fontSize: 11 }}>Dr. Priya Sharma</strong>
              <small style={{ color: 'var(--teal-primary)' }}>Cardiology · Doctor</small>
            </button>

            <button
              type="button"
              className="starter-chip"
              style={{ textAlign: 'left', padding: '8px 10px', height: 'auto' }}
              onClick={() => selectDemoAccount('dr.mehta@metrohealth.org', 'DoctorPassword123!')}
            >
              <strong style={{ display: 'block', color: 'var(--text-primary)', fontSize: 11 }}>Dr. Rajesh Mehta</strong>
              <small style={{ color: 'var(--accent-research)' }}>Neurology · Doctor</small>
            </button>

            <button
              type="button"
              className="starter-chip"
              style={{ textAlign: 'left', padding: '8px 10px', height: 'auto' }}
              onClick={() => selectDemoAccount('dr.patel@metrohealth.org', 'DoctorPassword123!')}
            >
              <strong style={{ display: 'block', color: 'var(--text-primary)', fontSize: 11 }}>Dr. Anita Patel</strong>
              <small style={{ color: 'var(--text-muted)' }}>Internal Med · Doctor</small>
            </button>

            <button
              type="button"
              className="starter-chip"
              style={{ textAlign: 'left', padding: '8px 10px', height: 'auto' }}
              onClick={() => selectDemoAccount('admin@metrohealth.org', 'AdminPassword123!')}
            >
              <strong style={{ display: 'block', color: 'var(--text-primary)', fontSize: 11 }}>Sarah Jenkins</strong>
              <small style={{ color: 'var(--status-caution)' }}>Hospital Admin</small>
            </button>
          </div>
        </div>

        <div style={{ textAlign: 'center', marginTop: 18 }}>
          <button
            type="button"
            onClick={onCancel}
            style={{ fontSize: 12, color: 'var(--text-secondary)' }}
          >
            Cancel and Return to Public Overview
          </button>
        </div>
      </div>
    </div>
  )
}
