import React from 'react'
import {
  Activity,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  FileSearch,
  HeartPulse,
  History,
  Lock,
  ShieldAlert,
  ShieldCheck,
  Users
} from 'lucide-react'

interface LandingPageProps {
  onSignInClick: () => void
  onExploreDemo: () => void
}

export const LandingPage: React.FC<LandingPageProps> = ({ onSignInClick, onExploreDemo }) => {
  return (
    <div className="landing-shell">
      {/* Top Navigation */}
      <header className="landing-nav">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="brand-icon">
            <Activity size={20} strokeWidth={2.5} />
          </div>
          <div>
            <div className="brand-name">
              med<span>perplexity</span>
            </div>
            <div className="brand-badge">HOSPITAL CLINICAL INTELLIGENCE</div>
          </div>
        </div>

        <nav style={{ display: 'flex', alignItems: 'center', gap: 24, fontSize: 13, fontWeight: 600 }}>
          <a href="#clinical-intelligence" style={{ color: 'var(--text-secondary)' }}>Clinical Intelligence</a>
          <a href="#medical-research" style={{ color: 'var(--text-secondary)' }}>Medical Research</a>
          <a href="#for-hospitals" style={{ color: 'var(--text-secondary)' }}>For Hospitals</a>
          <a href="#security" style={{ color: 'var(--text-secondary)' }}>Safety & Verification</a>
        </nav>

        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-secondary" onClick={onExploreDemo}>
            Explore Demo
          </button>
          <button className="btn btn-primary" onClick={onSignInClick}>
            Hospital Sign In <ArrowRight size={14} />
          </button>
        </div>
      </header>

      {/* Hero Section */}
      <section className="landing-hero">
        <div>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 12px',
            borderRadius: 20,
            background: 'var(--teal-soft)',
            color: 'var(--teal-primary)',
            fontSize: 12,
            fontWeight: 700,
            marginBottom: 16
          }}>
            <ShieldCheck size={14} /> Grounded Clinical Intelligence for Hospitals
          </div>
          <h1 className="hero-headline">
            Clinical intelligence,<br />
            <span>grounded in medical evidence.</span>
          </h1>
          <p className="hero-statement">
            Bring patient context, peer-reviewed medical research, and deterministic safety checks
            into one unified platform built specifically for hospital clinicians and health systems.
          </p>

          <div className="hero-actions">
            <button className="btn btn-primary" style={{ padding: '12px 22px', fontSize: 14 }} onClick={onSignInClick}>
              Hospital Sign In <ArrowRight size={16} />
            </button>
            <button className="btn btn-secondary" style={{ padding: '12px 22px', fontSize: 14 }} onClick={onExploreDemo}>
              Launch Live Workspace
            </button>
          </div>

          <div style={{ display: 'flex', gap: 24, marginTop: 32, fontSize: 12, color: 'var(--text-secondary)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <CheckCircle2 size={16} color="var(--teal-primary)" /> Real NCBI PubMed Retrieval
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <CheckCircle2 size={16} color="var(--teal-primary)" /> Deterministic Safety Rules
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <CheckCircle2 size={16} color="var(--teal-primary)" /> Jan Aushadhi Savings
            </div>
          </div>
        </div>

        {/* Live Interface Preview Mockup */}
        <div style={{ position: 'relative' }}>
          <div className="card" style={{
            boxShadow: 'var(--shadow-lg)',
            border: '1px solid var(--border-strong)',
            background: 'var(--surface)',
            padding: 24
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="status-pill status-blocked">
                  <ShieldAlert size={14} /> Blocked: allergy
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>PAT-001 · Rahul Sharma (58y M)</span>
              </div>
              <span className="tag-chip">CYP2C19 / Allergy</span>
            </div>

            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6, color: 'var(--text-primary)' }}>
              Prescription Order: Aspirin 75mg
            </div>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 16 }}>
              Alert: Documented hypersensitivity to <strong>aspirin</strong>. Order blocked prior to execution by the deterministic patient safety layer.
            </p>

            <div style={{
              background: 'var(--surface-soft)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-md)',
              padding: 12,
              marginBottom: 14
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                <span>EVIDENCE SOURCE · PMID 38151234</span>
                <span style={{ color: 'var(--status-approved)', fontWeight: 700 }}>Direct Evidence</span>
              </div>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
                Dual Antiplatelet Therapy Strategies After PCI: Guideline Updates
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
                Journal of the American College of Cardiology (2023)
              </div>
            </div>

            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              paddingTop: 10,
              borderTop: '1px solid var(--border)',
              fontSize: 11,
              color: 'var(--text-muted)'
            }}>
              <span>Claim Support: <strong>1/1 Verified Quotes</strong></span>
              <span style={{ color: 'var(--teal-primary)', fontWeight: 600 }}>St. Jude Metropolitan Health System</span>
            </div>
          </div>
        </div>
      </section>

      {/* Core Capabilities */}
      <section id="clinical-intelligence" className="features-section">
        <div className="section-head">
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--teal-primary)', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 8 }}>
            Core Capabilities
          </div>
          <h2>Engineered for Clinical Verification</h2>
          <p>
            MedPerplexity separates clinical reasoning, deterministic safety rules, medical literature retrieval,
            and generic medicine pricing into explicit, verifiable layers.
          </p>
        </div>

        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon">
              <ShieldCheck size={22} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>Clinical Decision Support</h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              Evaluates documented patient allergies, duplicate therapies, and drug interactions using strict deterministic rules that cannot be overridden by LLM prose.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon" style={{ background: 'var(--accent-research-soft)', color: 'var(--accent-research)' }}>
              <BookOpen size={22} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>Independent Research Library</h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              Explore peer-reviewed PubMed literature independently of a patient record. Personalized by specialty with full abstract inspection and one-click saving.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <FileSearch size={22} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>Claim-Support Validation</h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              Verifies whether generated statements are grounded in exact abstract text from retrieved PubMed articles, distinguishing provenance from unverified speculation.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <History size={22} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>Full Auditability & History</h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              Every clinical assessment, safety flag, and tool step is recorded in SQLite persistence with timestamps and reasoning notes for clinical governance.
            </p>
          </div>
        </div>
      </section>

      {/* Hospital Offering Section */}
      <section id="for-hospitals" style={{ padding: '70px 40px', maxWidth: 1200, margin: '0 auto', width: '100%' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 50, alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--teal-primary)', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 8 }}>
              Hospital Enterprise Licensing
            </div>
            <h2 style={{ fontSize: 30, fontWeight: 800, marginBottom: 16, color: 'var(--text-primary)' }}>
              Centralized Hospital Access Management
            </h2>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: 20 }}>
              Hospitals purchase MedPerplexity and configure authorized departments. Administrators manage physician seats, configure specialty designations, and monitor clinical usage logs.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', gap: 12 }}>
                <Users size={18} color="var(--teal-primary)" style={{ flexShrink: 0, marginTop: 2 }} />
                <div>
                  <strong style={{ fontSize: 13 }}>Role-Based Access Control</strong>
                  <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Separate permissions for Doctors, Clinical Administrators, and Department Heads.</p>
                </div>
              </div>

              <div style={{ display: 'flex', gap: 12 }}>
                <Lock size={18} color="var(--teal-primary)" style={{ flexShrink: 0, marginTop: 2 }} />
                <div>
                  <strong style={{ fontSize: 13 }}>Enterprise Organization Isolation</strong>
                  <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Data isolation at the database layer ensures patient records and saved research remain strictly confidential to your hospital.</p>
                </div>
              </div>

              <div style={{ display: 'flex', gap: 12 }}>
                <HeartPulse size={18} color="var(--teal-primary)" style={{ flexShrink: 0, marginTop: 2 }} />
                <div>
                  <strong style={{ fontSize: 13 }}>Jan Aushadhi Generic Discovery</strong>
                  <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Integrated medicine catalog with 2,400+ products for instant price comparisons and generic equivalence awareness.</p>
                </div>
              </div>
            </div>
          </div>

          <div className="card" style={{ padding: 28, background: 'var(--surface-soft)' }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Demo Hospital Environment</h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 }}>
              The platform is pre-configured with the fictional <strong>St. Jude Metropolitan Health System</strong> and ready-to-test physician credentials:
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ padding: 12, background: 'var(--surface)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong>Dr. Priya Sharma, MD</strong>
                  <span className="tag-chip">Cardiology</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>dr.sharma@metrohealth.org · Doctor</div>
              </div>

              <div style={{ padding: 12, background: 'var(--surface)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong>Dr. Rajesh Mehta, MD</strong>
                  <span className="tag-chip">Neurology</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>dr.mehta@metrohealth.org · Doctor</div>
              </div>

              <div style={{ padding: 12, background: 'var(--surface)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong>Sarah Jenkins, MHA</strong>
                  <span className="tag-chip">Administration</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>admin@metrohealth.org · Hospital Admin</div>
              </div>
            </div>

            <button className="btn btn-primary" style={{ width: '100%', marginTop: 20 }} onClick={onSignInClick}>
              Sign In to Demo Hospital Account
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div>
          <strong>MedPerplexity</strong> · Clinical Intelligence Platform for Healthcare Organizations
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            Clinical decision support only. All recommendations require independent verification by a qualified physician.
          </div>
        </div>

        <div style={{ display: 'flex', gap: 20 }}>
          <a href="#clinical-intelligence">Platform</a>
          <a href="#security">Safety Standards</a>
          <button onClick={onSignInClick} style={{ color: 'var(--teal-primary)', fontWeight: 600 }}>Hospital Login</button>
        </div>
      </footer>
    </div>
  )
}
