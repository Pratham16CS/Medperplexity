import React, { useState } from 'react'
import {
  Check,
  HeartPulse,
  Moon,
  Save,
  Settings,
  Sun,
  User
} from 'lucide-react'
import type { HospitalUser } from '../types/clinical'
import { updateUserPreferences } from '../lib/api'

interface SettingsViewProps {
  user: HospitalUser
  theme: 'light' | 'dark'
  onThemeChange: (theme: 'light' | 'dark') => void
  onUserUpdated: (updatedUser: HospitalUser) => void
}

const SPECIALTY_OPTIONS = [
  'Cardiology',
  'Neurology',
  'Internal Medicine',
  'Oncology',
  'Endocrinology',
  'Nephrology',
  'Infectious Disease',
  'Pulmonology',
  'Gastroenterology',
]

export const SettingsView: React.FC<SettingsViewProps> = ({
  user,
  theme,
  onThemeChange,
  onUserUpdated,
}) => {
  const [specialty, setSpecialty] = useState(user.specialty || 'Cardiology')
  const [dateRange, setDateRange] = useState(user.preferred_date_range || '2018-present')
  const [savedSuccess, setSavedSuccess] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setSavedSuccess(false)

    try {
      await updateUserPreferences({
        specialty,
        preferred_date_range: dateRange,
        theme,
      })

      onUserUpdated({
        ...user,
        specialty,
        preferred_date_range: dateRange,
        theme,
      })
      setSavedSuccess(true)
      setTimeout(() => setSavedSuccess(false), 3000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-title-block">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, color: 'var(--teal-primary)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4 }}>
            <Settings size={14} /> Account & Preferences
          </div>
          <h1>Clinician Profile & Preferences</h1>
          <p>
            Manage your medical specialty focus, appearance settings, and hospital credentials.
          </p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        {/* Clinician Identity Profile */}
        <div className="card">
          <div className="card-title">
            <User size={16} color="var(--teal-primary)" />
            <span>Hospital Identity</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 14, margin: '16px 0 20px' }}>
            <div className="user-avatar" style={{ width: 48, height: 48, fontSize: 16 }}>
              {user.avatar_initials}
            </div>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 800 }}>{user.full_name}</h2>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                {user.designation} · {user.department}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Hospital Domain:</span>
              <strong>{user.organization.name}</strong>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Organization ID:</span>
              <span className="tag-chip">{user.organization.code}</span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Email Address:</span>
              <span>{user.email}</span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Platform Role:</span>
              <span className="tag-chip" style={{ textTransform: 'capitalize' }}>
                {user.role.replace('_', ' ')}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>License Level:</span>
              <strong style={{ color: 'var(--teal-primary)' }}>{user.organization.tier}</strong>
            </div>
          </div>
        </div>

        {/* Preferences Form */}
        <div className="card">
          <div className="card-title">
            <HeartPulse size={16} color="var(--teal-primary)" />
            <span>Research & Clinical Preferences</span>
          </div>

          <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
                Primary Specialty (Filters your Research Feed)
              </label>
              <select
                className="search-input"
                style={{ paddingLeft: 12 }}
                value={specialty}
                onChange={(e) => setSpecialty(e.target.value)}
              >
                {SPECIALTY_OPTIONS.map((spec) => (
                  <option key={spec} value={spec}>{spec}</option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
                Preferred Literature Date Range
              </label>
              <select
                className="search-input"
                style={{ paddingLeft: 12 }}
                value={dateRange}
                onChange={(e) => setDateRange(e.target.value)}
              >
                <option value="2020-present">Last 5 Years (2020 – Present)</option>
                <option value="2018-present">Last 7 Years (2018 – Present)</option>
                <option value="2015-present">Last 10 Years (2015 – Present)</option>
                <option value="all">All Available Publication Dates</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 8 }}>
                Theme & Interface Appearance
              </label>
              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  type="button"
                  className={`btn ${theme === 'light' ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ flex: 1 }}
                  onClick={() => onThemeChange('light')}
                >
                  <Sun size={15} /> Light Theme
                </button>
                <button
                  type="button"
                  className={`btn ${theme === 'dark' ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ flex: 1 }}
                  onClick={() => onThemeChange('dark')}
                >
                  <Moon size={15} /> Dark Theme
                </button>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 }}>
              {savedSuccess ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--status-approved)', fontSize: 12, fontWeight: 600 }}>
                  <Check size={16} /> Preferences updated successfully!
                </div>
              ) : <div />}

              <button type="submit" className="btn btn-primary" disabled={saving}>
                <Save size={15} /> {saving ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
