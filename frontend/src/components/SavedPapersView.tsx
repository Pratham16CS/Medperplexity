import React, { useEffect, useState } from 'react'
import {
  Bookmark,
  ExternalLink,
  LoaderCircle,
  Search,
  Trash2
} from 'lucide-react'
import type { HospitalUser, SavedPaper } from '../types/clinical'
import { fetchSavedPapers, removeSavedPaper } from '../lib/api'

interface SavedPapersViewProps {
  user: HospitalUser
  onNavigateToResearch: () => void
}

export const SavedPapersView: React.FC<SavedPapersViewProps> = ({
  user,
  onNavigateToResearch,
}) => {
  const [papers, setPapers] = useState<SavedPaper[]>([])
  const [searchTerm, setSearchTerm] = useState('')
  const [specialtyFilter, setSpecialtyFilter] = useState('All Specialties')
  const [loading, setLoading] = useState(true)

  const loadPapers = async () => {
    setLoading(true)
    try {
      const data = await fetchSavedPapers()
      setPapers(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadPapers()
  }, [])

  const handleRemove = async (pmid: string) => {
    try {
      await removeSavedPaper(pmid)
      setPapers((prev) => prev.filter((p) => p.pmid !== pmid))
    } catch {
      // Ignore
    }
  }

  const specialties = ['All Specialties', ...Array.from(new Set(papers.map((p) => p.specialty).filter(Boolean)))]

  const filtered = papers.filter((p) => {
    const matchesSpec = specialtyFilter === 'All Specialties' || p.specialty === specialtyFilter
    const term = searchTerm.toLowerCase()
    const matchesSearch =
      p.title.toLowerCase().includes(term) ||
      p.authors.toLowerCase().includes(term) ||
      p.pmid.includes(term) ||
      (p.notes || '').toLowerCase().includes(term)
    return matchesSpec && matchesSearch
  })

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-title-block">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, color: 'var(--accent-research)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4 }}>
            <Bookmark size={14} /> Doctor Collection
          </div>
          <h1>Saved Research Papers</h1>
          <p>
            Persisted peer-reviewed publications saved by {user.full_name} for clinical decision support.
          </p>
        </div>

        <button className="btn btn-primary" onClick={onNavigateToResearch}>
          Browse Medical Research
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ padding: '14px 20px', marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="search-input-wrap" style={{ flex: '1 1 300px' }}>
            <Search size={15} />
            <input
              type="text"
              className="search-input"
              placeholder="Filter your saved papers by title, author, or notes…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>

          <select
            value={specialtyFilter}
            onChange={(e) => setSpecialtyFilter(e.target.value)}
            style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border)',
              background: 'var(--surface-soft)',
              fontSize: 12,
            }}
          >
            {specialties.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 50, color: 'var(--text-muted)' }}>
          <LoaderCircle size={24} className="animate-spin" style={{ margin: '0 auto 10px' }} />
          <div>Loading your saved papers…</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {filtered.map((paper) => (
            <div key={paper.id} className="card paper-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div>
                  <div className="paper-title">{paper.title}</div>
                  <div className="paper-authors" style={{ marginTop: 4 }}>
                    {paper.authors}
                  </div>
                </div>

                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => handleRemove(paper.pmid)}
                  title="Remove from saved collection"
                >
                  <Trash2 size={13} />
                  <span>Remove</span>
                </button>
              </div>

              <div className="paper-meta-row">
                <span className="tag-chip" style={{ fontWeight: 600 }}>PMID {paper.pmid}</span>
                <span className="tag-chip">{paper.journal}</span>
                <span className="tag-chip">{paper.pub_date}</span>
                <span className="tag-chip" style={{ color: 'var(--teal-primary)' }}>{paper.specialty}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                  Saved {paper.saved_at.slice(0, 10)}
                </span>
              </div>

              <p className="paper-abstract">
                {paper.abstract}
              </p>

              {paper.notes && (
                <div style={{ padding: 10, background: 'var(--teal-soft)', borderRadius: 'var(--radius-sm)', border: '1px solid #c2e2dc', fontSize: 12, color: 'var(--teal-dark)' }}>
                  <strong>Clinician Note:</strong> {paper.notes}
                </div>
              )}

              <div className="paper-actions-row">
                <a
                  href={paper.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 12, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                >
                  View on PubMed <ExternalLink size={12} />
                </a>
              </div>
            </div>
          ))}

          {filtered.length === 0 && (
            <div className="card" style={{ textAlign: 'center', padding: 48, color: 'var(--text-muted)' }}>
              <Bookmark size={36} style={{ margin: '0 auto 12px', opacity: 0.5 }} />
              <h3>No saved papers found</h3>
              <p style={{ fontSize: 13, marginTop: 4, marginBottom: 16 }}>
                You have not saved any papers matching this search.
              </p>
              <button className="btn btn-primary" onClick={onNavigateToResearch}>
                Explore Research Library
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
