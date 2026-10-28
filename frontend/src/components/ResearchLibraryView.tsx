import { useEffect, useState } from 'react'
import {
  AlertCircle,
  BookOpen,
  Bookmark,
  ExternalLink,
  Eye,
  Filter,
  LoaderCircle,
  Search,
  X
} from 'lucide-react'
import type { HospitalUser, ResearchPaper } from '../types/clinical'
import {
  fetchSavedPapers,
  removeSavedPaper,
  saveResearchPaper,
  searchResearch
} from '../lib/api'

interface ResearchLibraryViewProps {
  user: HospitalUser
  initialSpecialty?: string
}

const SPECIALTIES = [
  'All Specialties',
  'Cardiology',
  'Neurology',
  'Internal Medicine',
  'Oncology',
  'Endocrinology',
  'Nephrology',
  'Infectious Disease',
]

const PUB_TYPES = [
  'All Types',
  'Clinical Trial',
  'Systematic Review',
  'Meta-Analysis',
  'Guideline',
]

export const ResearchLibraryView: React.FC<ResearchLibraryViewProps> = ({
  user,
  initialSpecialty,
}) => {
  const [selectedSpecialty, setSelectedSpecialty] = useState<string>(
    initialSpecialty || user.specialty || 'Cardiology'
  )
  const [pubType, setPubType] = useState<string>('All Types')
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [papers, setPapers] = useState<ResearchPaper[]>([])
  const [savedPmids, setSavedPmids] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sourceNote, setSourceNote] = useState<string | null>(null)
  const [selectedPaper, setSelectedPaper] = useState<ResearchPaper | null>(null)
  const [noteText, setNoteText] = useState('')

  const loadPapers = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await searchResearch({
        query: searchQuery,
        specialty: selectedSpecialty,
        publication_type: pubType,
        limit: 15,
      })
      setPapers(res.papers)
      setSourceNote(res.error_note || null)
    } catch (e: any) {
      setError(e?.message || 'Failed to search PubMed research.')
    } finally {
      setLoading(false)
    }
  }

  const loadSavedPmids = async () => {
    try {
      const saved = await fetchSavedPapers()
      setSavedPmids(new Set(saved.map((p) => p.pmid)))
    } catch {
      // Ignore
    }
  }

  useEffect(() => {
    void loadSavedPmids()
    void loadPapers()
  }, [selectedSpecialty, pubType])

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    void loadPapers()
  }

  const handleToggleSave = async (paper: ResearchPaper) => {
    const isSaved = savedPmids.has(paper.pmid)
    try {
      if (isSaved) {
        await removeSavedPaper(paper.pmid)
        setSavedPmids((prev) => {
          const next = new Set(prev)
          next.delete(paper.pmid)
          return next
        })
      } else {
        await saveResearchPaper(paper, noteText)
        setSavedPmids((prev) => new Set([...prev, paper.pmid]))
        setNoteText('')
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to update saved status.')
    }
  }

  return (
    <div className="page-container">
      {/* Header */}
      <div className="page-header">
        <div className="page-title-block">
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, color: 'var(--accent-research)', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 4 }}>
            <BookOpen size={14} /> Medical Evidence & Literature
          </div>
          <h1>Independent Research Library</h1>
          <p>
            Explore peer-reviewed publications and clinical trials across specialties — independent of a selected patient.
          </p>
        </div>
      </div>

      {/* Specialty Filter Tabs */}
      <div className="research-filters-bar">
        {SPECIALTIES.map((spec) => (
          <button
            key={spec}
            className={`filter-tab ${selectedSpecialty === spec ? 'active' : ''}`}
            onClick={() => setSelectedSpecialty(spec)}
          >
            {spec}
            {spec === user.specialty && ' (Your Specialty)'}
          </button>
        ))}
      </div>

      {/* Search & Filter Controls */}
      <div className="card" style={{ padding: '16px 20px', marginBottom: 20 }}>
        <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="search-input-wrap" style={{ flex: '1 1 300px' }}>
            <Search size={15} />
            <input
              type="text"
              className="search-input"
              placeholder="Search by topic, drug name, clinical trial, or PMID…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Filter size={14} color="var(--text-muted)" />
            <select
              value={pubType}
              onChange={(e) => setPubType(e.target.value)}
              style={{
                padding: '8px 12px',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border)',
                background: 'var(--surface-soft)',
                fontSize: 12,
              }}
            >
              {PUB_TYPES.map((pt) => (
                <option key={pt} value={pt}>{pt}</option>
              ))}
            </select>
          </div>

          <button type="submit" className="btn btn-primary btn-sm" disabled={loading}>
            {loading ? <LoaderCircle size={14} className="animate-spin" /> : <Search size={14} />}
            <span>Search PubMed</span>
          </button>
        </form>

        {sourceNote && (
          <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <AlertCircle size={13} color="var(--status-caution)" />
            <span>{sourceNote}</span>
          </div>
        )}
      </div>

      {error && (
        <div style={{ padding: 12, background: 'var(--status-blocked-bg)', color: 'var(--status-blocked)', borderRadius: 'var(--radius-md)', marginBottom: 16, fontSize: 12 }}>
          {error}
        </div>
      )}

      {/* Results List */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
            Showing {papers.length} publications for <em>{selectedSpecialty}</em>
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 50, color: 'var(--text-muted)' }}>
            <LoaderCircle size={28} className="animate-spin" style={{ margin: '0 auto 12px' }} />
            <div>Querying PubMed medical literature…</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {papers.map((paper) => {
              const isSaved = savedPmids.has(paper.pmid)
              return (
                <div key={paper.pmid} className="card paper-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                    <div>
                      <div className="paper-title">{paper.title}</div>
                      <div className="paper-authors" style={{ marginTop: 4 }}>
                        {paper.authors}
                      </div>
                    </div>
                    <button
                      className={`btn btn-sm ${isSaved ? 'btn-secondary' : 'btn-primary'}`}
                      onClick={() => handleToggleSave(paper)}
                      title={isSaved ? 'Remove from saved' : 'Save to my papers'}
                      style={{ flexShrink: 0 }}
                    >
                      <Bookmark size={13} fill={isSaved ? 'currentColor' : 'none'} />
                      <span>{isSaved ? 'Saved' : 'Save'}</span>
                    </button>
                  </div>

                  <div className="paper-meta-row">
                    <span className="tag-chip" style={{ fontWeight: 600 }}>PMID {paper.pmid}</span>
                    <span className="tag-chip">{paper.journal}</span>
                    <span className="tag-chip">{paper.pub_date}</span>
                    {paper.specialty && <span className="tag-chip" style={{ color: 'var(--teal-primary)' }}>{paper.specialty}</span>}
                    {paper.evidence_type && <span className="tag-chip" style={{ background: 'var(--accent-research-soft)', color: 'var(--accent-research)' }}>{paper.evidence_type}</span>}
                  </div>

                  <p className="paper-abstract">
                    {paper.abstract}
                  </p>

                  <div className="paper-actions-row">
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => setSelectedPaper(paper)}
                    >
                      <Eye size={13} /> Inspect Full Abstract
                    </button>

                    <a
                      href={paper.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ fontSize: 12, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                    >
                      Official NCBI Record <ExternalLink size={12} />
                    </a>
                  </div>
                </div>
              )
            })}

            {papers.length === 0 && (
              <div className="card" style={{ textAlign: 'center', padding: 48, color: 'var(--text-muted)' }}>
                <BookOpen size={36} style={{ margin: '0 auto 12px', opacity: 0.5 }} />
                <h3>No publications found for this query</h3>
                <p style={{ fontSize: 13, marginTop: 4 }}>
                  Try broadening your search terms or selecting another medical specialty.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Paper Detail Modal */}
      {selectedPaper && (
        <div className="modal-overlay" onClick={() => setSelectedPaper(null)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span className="tag-chip" style={{ fontWeight: 700 }}>PMID {selectedPaper.pmid}</span>
              <button onClick={() => setSelectedPaper(null)}>
                <X size={18} />
              </button>
            </div>

            <h2 style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.35, marginBottom: 10 }}>
              {selectedPaper.title}
            </h2>

            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
              <strong>Authors:</strong> {selectedPaper.authors}<br />
              <strong>Journal:</strong> {selectedPaper.journal} ({selectedPaper.pub_date})
              {selectedPaper.doi && <div><strong>DOI:</strong> {selectedPaper.doi}</div>}
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
                Abstract
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6, background: 'var(--surface-soft)', padding: 14, borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                {selectedPaper.abstract}
              </div>
            </div>

            {/* Clinician Note Input */}
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
                Personal Clinician Note (Saved to your account)
              </label>
              <textarea
                style={{ width: '100%', padding: 8, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface-soft)', fontSize: 12 }}
                rows={2}
                placeholder="e.g. Relevant for patient hypertension clinic follow-ups…"
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 14, borderTop: '1px solid var(--border)' }}>
              <a
                href={selectedPaper.url}
                target="_blank"
                rel="noreferrer"
                className="btn btn-secondary btn-sm"
              >
                Open in PubMed <ExternalLink size={13} />
              </a>

              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  void handleToggleSave(selectedPaper)
                  setSelectedPaper(null)
                }}
              >
                <Bookmark size={13} fill={savedPmids.has(selectedPaper.pmid) ? 'currentColor' : 'none'} />
                <span>{savedPmids.has(selectedPaper.pmid) ? 'Remove from Saved' : 'Save to My Collection'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
