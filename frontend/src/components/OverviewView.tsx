import React, { useEffect, useState } from 'react'
import {
  ArrowRight,
  BookOpen,
  Bookmark,
  ExternalLink,
  HeartPulse,
  History,
  Plus,
  ShieldCheck,
  Users
} from 'lucide-react'
import type {
  AssessmentHistoryItem,
  HospitalUser,
  Patient,
  ResearchPaper,
  SavedPaper
} from '../types/clinical'
import { fetchAssessments, fetchSavedPapers, saveResearchPaper, searchResearch } from '../lib/api'

interface OverviewViewProps {
  user: HospitalUser
  patients: Patient[]
  onNavigate: (view: string, extra?: any) => void
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  user,
  patients,
  onNavigate
}) => {
  const [assessments, setAssessments] = useState<AssessmentHistoryItem[]>([])
  const [savedPapers, setSavedPapers] = useState<SavedPaper[]>([])
  const [specialtyPapers, setSpecialtyPapers] = useState<ResearchPaper[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    Promise.allSettled([
      fetchAssessments({ limit: 5 }),
      fetchSavedPapers(),
      searchResearch({ specialty: user.specialty, limit: 3 })
    ]).then(([asmRes, savedRes, researchRes]) => {
      if (cancelled) return
      if (asmRes.status === 'fulfilled') setAssessments(asmRes.value)
      if (savedRes.status === 'fulfilled') setSavedPapers(savedRes.value)
      if (researchRes.status === 'fulfilled') setSpecialtyPapers(researchRes.value.papers)
      setLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [user.specialty])

  const handleQuickSave = async (paper: ResearchPaper) => {
    try {
      await saveResearchPaper(paper)
      const updated = await fetchSavedPapers()
      setSavedPapers(updated)
    } catch {
      // Ignore
    }
  }

  const getGreeting = () => {
    const hour = new Date().getHours()
    if (hour < 12) return 'Good morning'
    if (hour < 17) return 'Good afternoon'
    return 'Good evening'
  }

  return (
    <div className="page-container">
      {/* Welcome Area */}
      <div className="page-header">
        <div className="page-title-block">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, color: 'var(--teal-primary)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4 }}>
            <HeartPulse size={14} /> Clinical Intelligence Overview
          </div>
          <h1>{getGreeting()}, {user.full_name}</h1>
          <p>{user.designation} · {user.department} · {user.organization.name}</p>
        </div>

        <div className="page-header-actions">
          <button className="btn btn-secondary" onClick={() => onNavigate('research')}>
            <BookOpen size={15} /> Browse Research
          </button>
          <button className="btn btn-primary" onClick={() => onNavigate('workspace')}>
            <Plus size={16} /> New Assessment
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="metrics-grid">
        <div className="card metric-card">
          <div className="metric-top">
            <span className="metric-label">Configured Patients</span>
            <div className="metric-icon-wrap" style={{ background: 'var(--teal-soft)', color: 'var(--teal-primary)' }}>
              <Users size={18} />
            </div>
          </div>
          <div className="metric-val">{patients.length}</div>
          <div className="metric-sub">Active hospital patient records</div>
        </div>

        <div className="card metric-card">
          <div className="metric-top">
            <span className="metric-label">Saved Research Papers</span>
            <div className="metric-icon-wrap" style={{ background: 'var(--accent-research-soft)', color: 'var(--accent-research)' }}>
              <Bookmark size={18} />
            </div>
          </div>
          <div className="metric-val">{savedPapers.length}</div>
          <div className="metric-sub">Curated literature in your collection</div>
        </div>

        <div className="card metric-card">
          <div className="metric-top">
            <span className="metric-label">Past Assessments</span>
            <div className="metric-icon-wrap" style={{ background: 'var(--teal-soft)', color: 'var(--teal-primary)' }}>
              <History size={18} />
            </div>
          </div>
          <div className="metric-val">{assessments.length}</div>
          <div className="metric-sub">Recorded in hospital audit log</div>
        </div>

        <div className="card metric-card">
          <div className="metric-top">
            <span className="metric-label">Enterprise License</span>
            <div className="metric-icon-wrap" style={{ background: 'var(--status-approved-bg)', color: 'var(--status-approved)' }}>
              <ShieldCheck size={18} />
            </div>
          </div>
          <div className="metric-val" style={{ fontSize: 18, paddingTop: 4 }}>
            {user.organization.tier}
          </div>
          <div className="metric-sub">{user.organization.code} · Active hospital seat</div>
        </div>
      </div>

      {/* Main Grid: Research Highlights & Recent Assessments */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 24 }}>
        {/* Specialty Research Highlights */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">
                <BookOpen size={16} color="var(--accent-research)" />
                <span>{user.specialty} Research Highlights</span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                Peer-reviewed literature curated for your specialty designation.
              </p>
            </div>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onNavigate('research', { specialty: user.specialty })}
            >
              View All <ArrowRight size={13} />
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {specialtyPapers.map((paper) => {
              const isSaved = savedPapers.some((sp) => sp.pmid === paper.pmid)
              return (
                <div
                  key={paper.pmid}
                  style={{
                    padding: 14,
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)',
                    background: 'var(--surface-soft)'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                    <span>PMID {paper.pmid} · {paper.journal} ({paper.pub_date})</span>
                    <span className="tag-chip">{paper.specialty}</span>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.4 }}>
                    {paper.title}
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '6px 0 10px', lineHeight: 1.5 }}>
                    {paper.abstract.slice(0, 160)}…
                  </p>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <a
                      href={paper.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ fontSize: 11, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                    >
                      PubMed Citation <ExternalLink size={12} />
                    </a>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleQuickSave(paper)}
                      disabled={isSaved}
                    >
                      <Bookmark size={12} fill={isSaved ? 'currentColor' : 'none'} />
                      {isSaved ? 'Saved' : 'Save Paper'}
                    </button>
                  </div>
                </div>
              )
            })}

            {specialtyPapers.length === 0 && !loading && (
              <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)', fontSize: 13 }}>
                No specialty research loaded. Use the Research Library to search PubMed.
              </div>
            )}
          </div>
        </div>

        {/* Recent Assessments Preview */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">
                <History size={16} color="var(--teal-primary)" />
                <span>Recent Assessments</span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                Patient decision-support queries and deterministic safety checks.
              </p>
            </div>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onNavigate('assessments')}
            >
              View Full History <ArrowRight size={13} />
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {assessments.slice(0, 4).map((item) => {
              const statusClass = `status-${item.status}`
              return (
                <div
                  key={item.id}
                  style={{
                    padding: 12,
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)',
                    background: 'var(--surface-soft)',
                    cursor: 'pointer'
                  }}
                  onClick={() => onNavigate('assessments', { selectedId: item.id })}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span className={`status-pill ${statusClass}`} style={{ fontSize: 10, padding: '2px 8px' }}>
                      {item.status.toUpperCase()}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {item.patient_id} · {item.created_at.slice(0, 10)}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
                    {item.query}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 3 }}>
                    {item.title}
                  </div>
                </div>
              )
            })}

            {assessments.length === 0 && !loading && (
              <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)', fontSize: 13 }}>
                No recent assessments recorded. Run an assessment in the Clinical Workspace to begin.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
