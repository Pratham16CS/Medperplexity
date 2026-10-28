import { useEffect, useState } from 'react'
import {
  Activity,
  BookOpen,
  Bookmark,
  Building,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  User,
  Users,
  X
} from 'lucide-react'

import type { HospitalUser, Patient } from './types/clinical'
import { fetchCurrentUser, fetchPatients, logout } from './lib/api'
import { DEMO_PATIENTS } from './lib/demoPatients'

import { LandingPage } from './components/LandingPage'
import { LoginPage } from './components/LoginPage'
import { OverviewView } from './components/OverviewView'
import { ClinicalWorkspaceView } from './components/ClinicalWorkspaceView'
import { ResearchLibraryView } from './components/ResearchLibraryView'
import { SavedPapersView } from './components/SavedPapersView'
import { AssessmentsView } from './components/AssessmentsView'
import { AuditView } from './components/AuditView'
import { HospitalAdminView } from './components/HospitalAdminView'
import { SettingsView } from './components/SettingsView'

export default function App() {
  const [currentUser, setCurrentUser] = useState<HospitalUser | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [showLogin, setShowLogin] = useState(false)
  const [activeView, setActiveView] = useState<string>('overview')
  const [navigationPayload, setNavigationPayload] = useState<any>(null)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    return (localStorage.getItem('medperplexity_theme') as 'light' | 'dark') || 'light'
  })
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [patients, setPatients] = useState<Patient[]>(() => DEMO_PATIENTS)
  const [selectedPatientId, setSelectedPatientId] = useState<string>('PAT-001')
  const [patientsLoading, setPatientsLoading] = useState(false)
  const [patientsError, setPatientsError] = useState('')
  const [userMenuOpen, setUserMenuOpen] = useState(false)

  // Initialize theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('medperplexity_theme', theme)
  }, [theme])

  // Check existing session on load
  useEffect(() => {
    fetchCurrentUser()
      .then((user) => {
        if (user) {
          setCurrentUser(user)
          if (user.theme === 'light' || user.theme === 'dark') {
            setTheme(user.theme)
          }
        }
      })
      .finally(() => setAuthChecked(true))
  }, [])

  // Load configured patients from backend API with fallback to built-in demo records
  const loadPatients = () => {
    setPatientsLoading(true)
    fetchPatients()
      .then((pts) => {
        if (pts.length > 0) {
          setPatients(pts)
          setPatientsError('')
          setSelectedPatientId((curr) => (pts.some((p) => p.id === curr) ? curr : pts[0].id))
        } else {
          setPatients(DEMO_PATIENTS)
        }
      })
      .catch((err) => {
        console.warn('Backend patient sync note:', err)
        setPatients(DEMO_PATIENTS)
      })
      .finally(() => setPatientsLoading(false))
  }

  useEffect(() => {
    loadPatients()
  }, [currentUser])

  const handleSignOut = async () => {
    await logout()
    setCurrentUser(null)
    setActiveView('overview')
    setUserMenuOpen(false)
  }

  const handleNavigate = (view: string, payload?: any) => {
    setActiveView(view)
    setNavigationPayload(payload || null)
    setSidebarOpen(false)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  if (!authChecked) {
    return (
      <div style={{ height: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg-main)' }}>
        <div style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
          <Activity size={32} color="var(--teal-primary)" className="animate-spin" style={{ margin: '0 auto 12px' }} />
          <div>Connecting to MedPerplexity Hospital Platform…</div>
        </div>
      </div>
    )
  }

  // If user is not authenticated, render public hospital landing page
  if (!currentUser) {
    return (
      <div data-theme={theme}>
        <LandingPage
          onSignInClick={() => setShowLogin(true)}
          onExploreDemo={() => setShowLogin(true)}
        />
        {showLogin && (
          <LoginPage
            onSuccess={(user) => {
              setCurrentUser(user)
              setShowLogin(false)
            }}
            onCancel={() => setShowLogin(false)}
          />
        )}
      </div>
    )
  }

  const isAdmin = currentUser.role === 'hospital_admin'

  return (
    <div className="app-container" data-theme={theme}>
      {/* Mobile Scrim */}
      {sidebarOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.6)',
            zIndex: 35,
          }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar (21st.dev dashboard-2 style) */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="brand-header">
          <div className="brand-icon">
            <Activity size={20} strokeWidth={2.5} />
          </div>
          <div className="brand-titles">
            <div className="brand-name">
              med<span>perplexity</span>
            </div>
            <div className="brand-badge">CLINICAL INTELLIGENCE</div>
          </div>
          {sidebarOpen && (
            <button onClick={() => setSidebarOpen(false)} style={{ color: 'var(--sidebar-text-muted)' }}>
              <X size={18} />
            </button>
          )}
        </div>

        {/* Hospital Identity Card */}
        <div className="org-selector-card">
          <div className="org-avatar">
            <Building size={14} />
          </div>
          <div className="org-info">
            <div className="org-info-title">{currentUser.organization.name}</div>
            <div className="org-info-subtitle">{currentUser.organization.tier}</div>
          </div>
        </div>

        {/* Main Navigation */}
        <div className="nav-section-title">Workspace</div>
        <nav className="nav-menu">
          <button
            className={`nav-button ${activeView === 'overview' ? 'active' : ''}`}
            onClick={() => handleNavigate('overview')}
          >
            <LayoutDashboard size={16} />
            <span>Overview</span>
          </button>

          <button
            className={`nav-button ${activeView === 'workspace' ? 'active' : ''}`}
            onClick={() => handleNavigate('workspace')}
          >
            <ShieldCheck size={16} />
            <span>Clinical Workspace</span>
          </button>

          <button
            className={`nav-button ${activeView === 'research' ? 'active' : ''}`}
            onClick={() => handleNavigate('research')}
          >
            <BookOpen size={16} />
            <span>Research Library</span>
          </button>

          <button
            className={`nav-button ${activeView === 'saved-papers' ? 'active' : ''}`}
            onClick={() => handleNavigate('saved-papers')}
          >
            <Bookmark size={16} />
            <span>Saved Papers</span>
          </button>

          <button
            className={`nav-button ${activeView === 'assessments' ? 'active' : ''}`}
            onClick={() => handleNavigate('assessments')}
          >
            <History size={16} />
            <span>Recent Assessments</span>
          </button>

          <button
            className={`nav-button ${activeView === 'audit' ? 'active' : ''}`}
            onClick={() => handleNavigate('audit')}
          >
            <CheckCircle2 size={16} />
            <span>Audit History</span>
          </button>

          {isAdmin && (
            <>
              <div className="nav-section-title" style={{ marginTop: 14 }}>Administration</div>
              <button
                className={`nav-button ${activeView === 'admin' ? 'active' : ''}`}
                onClick={() => handleNavigate('admin')}
              >
                <Users size={16} />
                <span>Hospital Admin</span>
              </button>
            </>
          )}
        </nav>

        {/* Sidebar Footer */}
        <div className="sidebar-footer">
          <button
            className={`nav-button ${activeView === 'settings' ? 'active' : ''}`}
            onClick={() => handleNavigate('settings')}
          >
            <Settings size={16} />
            <span>Settings & Profile</span>
          </button>

          <div className="user-profile-pill">
            <div className="user-avatar">{currentUser.avatar_initials}</div>
            <div className="user-meta">
              <div className="user-meta-name">{currentUser.full_name}</div>
              <div className="user-meta-role">{currentUser.designation}</div>
            </div>
            <button
              onClick={handleSignOut}
              style={{ color: 'var(--sidebar-text-muted)', padding: 4 }}
              title="Sign out of hospital session"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Wrapper */}
      <div className="main-wrapper">
        {/* Topbar */}
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="mobile-toggle"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open sidebar"
            >
              <Menu size={20} />
            </button>

            <div className="breadcrumbs">
              <span>{currentUser.organization.name}</span>
              <ChevronRight size={13} />
              <strong style={{ textTransform: 'capitalize' }}>
                {activeView.replace('-', ' ')}
              </strong>
            </div>
          </div>

          <div className="topbar-actions">
            <div className="hospital-license-pill">
              <ShieldCheck size={13} />
              <span>{currentUser.organization.tier}</span>
            </div>

            <button
              className="topbar-btn"
              onClick={() => handleNavigate('research')}
              title="Search Medical Literature"
            >
              <Search size={16} />
            </button>

            <button
              className="topbar-btn"
              onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
              title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
            >
              {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
            </button>

            {/* User Dropdown */}
            <div style={{ position: 'relative' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              >
                <span>{currentUser.avatar_initials}</span>
                <ChevronDown size={13} />
              </button>

              {userMenuOpen && (
                <div
                  className="card"
                  style={{
                    position: 'absolute',
                    right: 0,
                    top: '100%',
                    marginTop: 6,
                    width: 220,
                    padding: 8,
                    zIndex: 50,
                    boxShadow: 'var(--shadow-lg)'
                  }}
                >
                  <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)' }}>
                    <strong>{currentUser.full_name}</strong>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{currentUser.email}</div>
                  </div>
                  <button
                    className="nav-button"
                    onClick={() => {
                      setUserMenuOpen(false)
                      handleNavigate('settings')
                    }}
                  >
                    <User size={14} /> Profile & Preferences
                  </button>
                  <button
                    className="nav-button"
                    style={{ color: 'var(--status-blocked)' }}
                    onClick={handleSignOut}
                  >
                    <LogOut size={14} /> Sign Out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* View Router */}
        <main style={{ flex: 1 }}>
          {activeView === 'overview' && (
            <OverviewView
              user={currentUser}
              patients={patients}
              onNavigate={handleNavigate}
            />
          )}

          {activeView === 'workspace' && (
            <ClinicalWorkspaceView
              user={currentUser}
              patients={patients}
              activePatientId={selectedPatientId}
              onSelectPatient={setSelectedPatientId}
              patientsLoading={patientsLoading}
              patientsError={patientsError}
              onRefreshPatients={loadPatients}
            />
          )}

          {activeView === 'research' && (
            <ResearchLibraryView
              user={currentUser}
              initialSpecialty={navigationPayload?.specialty}
            />
          )}

          {activeView === 'saved-papers' && (
            <SavedPapersView
              user={currentUser}
              onNavigateToResearch={() => handleNavigate('research')}
            />
          )}

          {activeView === 'assessments' && (
            <AssessmentsView
              user={currentUser}
              initialSelectedId={navigationPayload?.selectedId}
            />
          )}

          {activeView === 'audit' && (
            <AuditView user={currentUser} />
          )}

          {activeView === 'admin' && isAdmin && (
            <HospitalAdminView user={currentUser} />
          )}

          {activeView === 'settings' && (
            <SettingsView
              user={currentUser}
              theme={theme}
              onThemeChange={setTheme}
              onUserUpdated={setCurrentUser}
            />
          )}
        </main>
      </div>
    </div>
  )
}
