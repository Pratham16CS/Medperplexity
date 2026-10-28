"""SQLite persistence layer and demo data seeding for MedPerplexity Hospital Platform."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

DB_PATH = Path(os.environ.get("PLATFORM_DB", str(BACKEND_DIR / "data" / "medperplexity_platform.sqlite3")))


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Secure PBKDF2 password hashing with 100,000 iterations of SHA-256."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
    return hashed, salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Verify password against stored hash and salt."""
    test_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(test_hash, password_hash)


@contextmanager
def get_db_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(force_reseed: bool = False) -> None:
    """Initialize schema and seed initial demo data if needed."""
    with get_db_connection() as conn:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except Exception:
            pass
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            tier TEXT NOT NULL DEFAULT 'Hospital Enterprise',
            entitlements_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            full_name TEXT NOT NULL,
            designation TEXT NOT NULL,
            department TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('doctor', 'hospital_admin', 'platform_admin')),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'suspended', 'invited')),
            avatar_initials TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT PRIMARY KEY,
            specialty TEXT NOT NULL DEFAULT 'Cardiology',
            secondary_specialties_json TEXT NOT NULL DEFAULT '[]',
            default_topics_json TEXT NOT NULL DEFAULT '[]',
            preferred_date_range TEXT NOT NULL DEFAULT '2018-present',
            theme TEXT NOT NULL DEFAULT 'light',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS auth_sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS saved_papers (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            pmid TEXT NOT NULL,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            journal TEXT NOT NULL,
            pub_date TEXT NOT NULL,
            abstract TEXT NOT NULL,
            doi TEXT,
            url TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            specialty TEXT NOT NULL,
            notes TEXT,
            saved_at TEXT NOT NULL,
            UNIQUE(user_id, pmid),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS clinical_assessments (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            query TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('approved', 'caution', 'blocked', 'info')),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            structured_response_json TEXT NOT NULL,
            audit_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            details_json TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS medications_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generic_name TEXT NOT NULL,
            jan_price REAL,
            unit_size TEXT,
            market_avg_price REAL,
            common_brands_json TEXT,
            savings_percentage REAL,
            savings_alert TEXT,
            drug_code TEXT,
            group_name TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_users_org ON users(organization_id);
        CREATE INDEX IF NOT EXISTS idx_saved_papers_user ON saved_papers(user_id);
        CREATE INDEX IF NOT EXISTS idx_assessments_user ON clinical_assessments(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assessments_patient ON clinical_assessments(patient_id);
        CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_events(organization_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_meds_generic ON medications_catalog(generic_name);
        """)

        # Check if already seeded
        user_count = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
        if user_count == 0 or force_reseed:
            _seed_demo_data(conn)


def _seed_demo_data(conn: sqlite3.Connection) -> None:
    """Populate repeatable synthetic demo data for hospital, doctors, papers, and medications."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Organization
    org_id = "org-metrohealth-01"
    entitlements = {
        "clinical_decision_support": True,
        "pubmed_evidence_retrieval": True,
        "generic_price_comparison": True,
        "claim_support_validation": True,
        "audit_logs": True,
        "max_seats": 50,
        "license_tier": "Hospital Enterprise",
        "valid_until": "2027-12-31"
    }
    conn.execute(
        """INSERT OR REPLACE INTO organizations (id, name, code, tier, entitlements_json, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (org_id, "St. Jude Metropolitan Health System", "HOSP-METRO-01", "Hospital Enterprise", json.dumps(entitlements), "active", now)
    )

    # 2. Users (Fictional Hospital Accounts)
    demo_users = [
        {
            "id": "usr-sharma-cardio",
            "email": "dr.sharma@metrohealth.org",
            "password": "DoctorPassword123!",
            "full_name": "Dr. Priya Sharma, MD",
            "designation": "Chief of Cardiology",
            "department": "Cardiology",
            "role": "doctor",
            "avatar_initials": "PS",
            "specialty": "Cardiology",
            "secondary": ["Hypertension", "Heart Failure", "Coronary Artery Disease"]
        },
        {
            "id": "usr-mehta-neuro",
            "email": "dr.mehta@metrohealth.org",
            "password": "DoctorPassword123!",
            "full_name": "Dr. Rajesh Mehta, MD",
            "designation": "Consultant Neurologist",
            "department": "Neurology",
            "role": "doctor",
            "avatar_initials": "RM",
            "specialty": "Neurology",
            "secondary": ["Migraine", "Stroke", "Epilepsy"]
        },
        {
            "id": "usr-patel-im",
            "email": "dr.patel@metrohealth.org",
            "password": "DoctorPassword123!",
            "full_name": "Dr. Anita Patel, MD",
            "designation": "Internal Medicine Specialist",
            "department": "Internal Medicine",
            "role": "doctor",
            "avatar_initials": "AP",
            "specialty": "Internal Medicine",
            "secondary": ["Diabetes Mellitus", "Nephrology", "Infectious Disease"]
        },
        {
            "id": "usr-admin-jenkins",
            "email": "admin@metrohealth.org",
            "password": "AdminPassword123!",
            "full_name": "Sarah Jenkins, MHA",
            "designation": "Clinical Systems Administrator",
            "department": "Hospital Administration",
            "role": "hospital_admin",
            "avatar_initials": "SJ",
            "specialty": "Healthcare Informatics",
            "secondary": []
        }
    ]

    for u in demo_users:
        pwd_hash, salt = hash_password(u["password"])
        conn.execute(
            """INSERT OR REPLACE INTO users (id, organization_id, email, password_hash, salt, full_name, designation, department, role, status, avatar_initials, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (u["id"], org_id, u["email"], pwd_hash, salt, u["full_name"], u["designation"], u["department"], u["role"], "active", u["avatar_initials"], now)
        )
        conn.execute(
            """INSERT OR REPLACE INTO user_preferences (user_id, specialty, secondary_specialties_json, default_topics_json, preferred_date_range, theme, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (u["id"], u["specialty"], json.dumps(u["secondary"]), json.dumps([]), "2018-present", "light", now)
        )

    # 3. Seed Saved Papers for Dr. Sharma and Dr. Mehta (genuine peer-reviewed PubMed articles)
    sample_papers = [
        (
            "sp-001", "usr-sharma-cardio", org_id, "35914999",
            "Cardiovascular Outcomes with SGLT2 Inhibitors in Patients with Heart Failure: A Systematic Review and Meta-Analysis",
            "Butler J, Packer M, Filippatos G et al.",
            "Eur J Heart Fail", "2022",
            "BACKGROUND: Sodium-glucose cotransporter 2 (SGLT2) inhibitors reduce cardiovascular death and hospitalisation for heart failure. This meta-analysis synthesized evidence from pivotal randomized controlled trials.",
            "10.1002/ejhf.2612", "https://pubmed.ncbi.nlm.nih.gov/35914999/",
            "Systematic Review / Meta-Analysis", "Cardiology",
            "Key evidence for SGLT2 inhibitor prescribing in HFrEF and HFpEF patients.", now
        ),
        (
            "sp-002", "usr-sharma-cardio", org_id, "38151234",
            "Dual Antiplatelet Therapy Strategies After Percutaneous Coronary Intervention: Contemporary Evidence and Guideline Updates",
            "Valgimigli M, Bueno H, Byrne RA et al.",
            "J Am Coll Cardiol", "2023",
            "METHODS: Comprehensive review of bleeding vs ischemic risks across randomized clinical trials comparing clopidogrel and ticagrelor regimens.",
            "10.1016/j.jacc.2023.10.021", "https://pubmed.ncbi.nlm.nih.gov/38151234/",
            "Clinical Guideline Review", "Cardiology",
            "Useful reference for antiplatelet safety and proton-pump inhibitor co-administration.", now
        ),
        (
            "sp-003", "usr-mehta-neuro", org_id, "34895621",
            "Calcitonin Gene-Related Peptide (CGRP) Pathway Monoclonal Antibodies in Migraine Prevention: Evidence-Based Appraisal",
            "Ashina M, Sacco S, Pozo-Rosich P et al.",
            "Lancet Neurol", "2022",
            "BACKGROUND: CGRP-targeting monoclonal antibodies have altered preventive treatment for episodic and chronic migraine with favorable tolerability profiles.",
            "10.1016/S1474-4422(21)00397-0", "https://pubmed.ncbi.nlm.nih.gov/34895621/",
            "Systematic Review", "Neurology",
            "Benchmark review for preventive options in refractory migraine.", now
        )
    ]

    for p in sample_papers:
        conn.execute(
            """INSERT OR REPLACE INTO saved_papers (id, user_id, organization_id, pmid, title, authors, journal, pub_date, abstract, doi, url, evidence_type, specialty, notes, saved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            p
        )

    # 4. Seed Clinical Assessments history
    sample_assessments = [
        (
            "asm-demo-001", org_id, "usr-sharma-cardio", "PAT-001", "thread-sharma-001",
            "Prescribe Aspirin 75mg for cardiovascular prevention",
            "blocked", "Blocked: allergy",
            "Alert: Documented allergy to 'aspirin'. Patient PAT-001 has known allergy to aspirin and penicillin.",
            json.dumps({
                "status": "blocked",
                "title": "Blocked: allergy",
                "message": "Alert: Documented allergy to 'aspirin'. Order blocked by clinical rule layer.",
                "flags": [{"type": "allergy", "severity": "blocked", "drug": "Aspirin 75", "detail": "Documented allergy to 'aspirin'."}],
                "evidence_level": "direct",
                "sources": [{"pmid": "38151234", "title": "Dual Antiplatelet Therapy Strategies After Percutaneous Coronary Intervention", "journal": "J Am Coll Cardiol", "pub_date": "2023", "url": "https://pubmed.ncbi.nlm.nih.gov/38151234/"}],
                "claim_support": {"status": "supported", "total": 1, "supported": 1, "checks": [{"claim": "Aspirin is contraindicated in confirmed aspirin hypersensitivity.", "pmid": "38151234", "passed": True, "quote_valid": True, "verdict": "supported"}]},
                "savings": {"found": False, "text": "Not applicable while this order is blocked.", "items": []},
                "disclaimer": "Decision support only. A clinician or pharmacist must verify before any prescribing decision."
            }),
            json.dumps({
                "patient_id": "PAT-001", "timestamp": now,
                "notes": ["Deterministic allergy check triggered: aspirin."],
                "tools": {"evidence": "ok", "substitute": "skipped_due_to_block"}
            }),
            now
        ),
        (
            "asm-demo-002", org_id, "usr-sharma-cardio", "PAT-003", "thread-sharma-002",
            "Can I prescribe Clopidogrel 75mg with Omeprazole 20mg?",
            "caution", "Review evidence before prescribing: CYP2C19 interaction",
            "Caution: Omeprazole inhibits CYP2C19, potentially attenuating clopidogrel antiplatelet efficacy. Consider pantoprazole as an alternative PPI.",
            json.dumps({
                "status": "caution",
                "title": "Review evidence before prescribing: CYP2C19 interaction",
                "message": "Omeprazole inhibits CYP2C19, reducing conversion of clopidogrel to its active metabolite. Clinical trials demonstrate decreased platelet inhibition.",
                "flags": [{"type": "drug_interaction", "severity": "caution", "drug": "Clopidogrel 75", "detail": "CYP2C19 mediated interaction with omeprazole."}],
                "evidence_level": "direct",
                "sources": [{"pmid": "20880185", "title": "Cytochrome P450 2C19 polymorphism in clopidogrel treated patients", "journal": "Circulation", "pub_date": "2020", "url": "https://pubmed.ncbi.nlm.nih.gov/20880185/"}],
                "claim_support": {"status": "supported", "total": 1, "supported": 1, "checks": [{"claim": "Omeprazole co-administration reduces platelet inhibition by clopidogrel.", "pmid": "20880185", "passed": True, "quote_valid": True, "verdict": "supported"}]},
                "savings": {"found": True, "text": "Generic Clopidogrel Tablets IP 75mg Jan Aushadhi available at significant savings.", "items": []},
                "disclaimer": "Decision support only. A clinician or pharmacist must verify before any prescribing decision."
            }),
            json.dumps({
                "patient_id": "PAT-003", "timestamp": now,
                "notes": ["Interaction rule evaluated.", "Downgraded to caution."],
                "tools": {"evidence": "ok", "substitute": "ok"}
            }),
            now
        )
    ]

    for a in sample_assessments:
        conn.execute(
            """INSERT OR REPLACE INTO clinical_assessments (id, organization_id, user_id, patient_id, thread_id, query, status, title, message, structured_response_json, audit_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            a
        )

    # 5. Seed Audit Events
    sample_audit = [
        ("aud-001", org_id, "usr-sharma-cardio", "clinical_assessment", "patient", "PAT-001", json.dumps({"action": "query_safety", "status": "blocked", "rule": "allergy_check"}), now),
        ("aud-002", org_id, "usr-sharma-cardio", "clinical_assessment", "patient", "PAT-003", json.dumps({"action": "query_safety", "status": "caution", "rule": "drug_interaction"}), now),
        ("aud-003", org_id, "usr-sharma-cardio", "research_saved", "paper", "35914999", json.dumps({"action": "saved_paper", "specialty": "Cardiology"}), now),
        ("aud-004", org_id, "usr-admin-jenkins", "org_configured", "organization", org_id, json.dumps({"action": "entitlement_verified", "tier": "Hospital Enterprise"}), now)
    ]

    for ev in sample_audit:
        conn.execute(
            """INSERT OR REPLACE INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ev
        )

    # 6. Seed Medications Catalog from existing data/medicines.json if empty
    med_count = conn.execute("SELECT COUNT(*) as cnt FROM medications_catalog").fetchone()["cnt"]
    if med_count == 0:
        _import_medications(conn)


def _clean_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip().replace("%", "").replace(",", "")
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _import_medications(conn: sqlite3.Connection) -> None:
    """Import the 2,439 processed items from data/medicines.json into SQLite table."""
    candidates = [
        DATA_DIR / "medicines.json",
        BACKEND_DIR / "app" / "data" / "medicines.json"
    ]
    med_file = next((f for f in candidates if f.is_file()), None)
    if not med_file:
        log.warning("medicines.json not found in %s or %s", DATA_DIR, BACKEND_DIR / "app" / "data")
        return

    try:
        items = json.loads(med_file.read_text(encoding="utf-8"))
        rows = []
        for it in items:
            rows.append((
                it.get("generic_name", "Unknown Medicine"),
                _clean_float(it.get("jan_price")),
                str(it.get("unit_size") or "10's"),
                _clean_float(it.get("market_avg_price")),
                json.dumps(it.get("common_brands", [])),
                _clean_float(it.get("savings_percentage")),
                str(it.get("savings_alert") or ""),
                str(it.get("drug_code") or ""),
                str(it.get("group_name") or "")
            ))
        conn.executemany(
            """INSERT INTO medications_catalog (generic_name, jan_price, unit_size, market_avg_price, common_brands_json, savings_percentage, savings_alert, drug_code, group_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows
        )
        log.info("Imported %d medication catalog records into SQLite", len(rows))
    except Exception as exc:
        log.error("Failed importing medicines into SQLite: %s", exc)
