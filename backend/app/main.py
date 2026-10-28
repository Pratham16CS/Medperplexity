"""Enterprise Hospital Clinical Intelligence Platform API adapter.

Integrates the official MedPerplexity package with hospital authentication,
SQLite persistence, independent PubMed research discovery, medication catalog,
clinical assessment history, and hospital administration.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from medperplexity.agent import AgentDeps, MedAgent
from medperplexity.patients import PatientStore

from .auth import (
    LoginRequest,
    authenticate_user,
    create_session,
    delete_session,
    get_current_user,
    require_role,
)
from .db import get_db_connection, hash_password, init_db
from .research import (
    get_paper_details,
    get_saved_papers,
    remove_saved_paper,
    save_paper,
    search_research_papers,
)

log = logging.getLogger(__name__)

# Ensure DB is initialized and seeded on module import
init_db()

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent.parent

# Hospital department & doctor assignments for clinical patients
PATIENT_DOCTOR_ASSIGNMENTS: dict[str, dict[str, str]] = {
    "PAT-001": {
        "doctor_id": "usr-sharma-cardio",
        "doctor_name": "Dr. Priya Sharma, MD",
        "department": "Cardiology",
        "specialty": "Cardiology",
        "room_bed": "Ward 3B · Bed 04",
        "admission_status": "Inpatient Active",
    },
    "PAT-002": {
        "doctor_id": "usr-mehta-neuro",
        "doctor_name": "Dr. Rajesh Mehta, MD",
        "department": "Neurology",
        "specialty": "Neurology",
        "room_bed": "Neuro Ward · Bed 03",
        "admission_status": "Observation",
    },
    "PAT-003": {
        "doctor_id": "usr-sharma-cardio",
        "doctor_name": "Dr. Priya Sharma, MD",
        "department": "Cardiology",
        "specialty": "Cardiology",
        "room_bed": "CCU · Bed 02",
        "admission_status": "Critical Care",
    },
    "PAT-004": {
        "doctor_id": "usr-patel-im",
        "doctor_name": "Dr. Anita Patel, MD",
        "department": "Internal Medicine",
        "specialty": "Internal Medicine",
        "room_bed": "Ward 2A · Bed 09",
        "admission_status": "Inpatient Active",
    },
    "PAT-005": {
        "doctor_id": "usr-sharma-cardio",
        "doctor_name": "Dr. Priya Sharma, MD",
        "department": "Cardiology",
        "specialty": "Cardiology",
        "room_bed": "Ward 3B · Bed 08",
        "admission_status": "Inpatient Active",
    },
    "PAT-006": {
        "doctor_id": "usr-mehta-neuro",
        "doctor_name": "Dr. Rajesh Mehta, MD",
        "department": "Neurology",
        "specialty": "Neurology",
        "room_bed": "Day Care · Bed 05",
        "admission_status": "Day Unit",
    },
    "PAT-007": {
        "doctor_id": "usr-patel-im",
        "doctor_name": "Dr. Anita Patel, MD",
        "department": "Internal Medicine",
        "specialty": "Internal Medicine",
        "room_bed": "Ward 2A · Bed 14",
        "admission_status": "Inpatient Active",
    },
    "PAT-008": {
        "doctor_id": "usr-patel-im",
        "doctor_name": "Dr. Anita Patel, MD",
        "department": "Internal Medicine",
        "specialty": "Internal Medicine",
        "room_bed": "Ward 2A · Bed 18",
        "admission_status": "Observation",
    },
    "PAT-009": {
        "doctor_id": "usr-sharma-cardio",
        "doctor_name": "Dr. Priya Sharma, MD",
        "department": "Cardiology",
        "specialty": "Cardiology",
        "room_bed": "Ward 3B · Bed 12",
        "admission_status": "Inpatient Active",
    },
    "PAT-010": {
        "doctor_id": "usr-patel-im",
        "doctor_name": "Dr. Anita Patel, MD",
        "department": "Internal Medicine",
        "specialty": "Internal Medicine",
        "room_bed": "Maternity Ward 1 · Bed 04",
        "admission_status": "Antenatal Inpatient",
    },
    "PAT-011": {
        "doctor_id": "usr-mehta-neuro",
        "doctor_name": "Dr. Rajesh Mehta, MD",
        "department": "Neurology",
        "specialty": "Neurology",
        "room_bed": "Neuro Ward · Bed 07",
        "admission_status": "Outpatient Review",
    },
    "PAT-012": {
        "doctor_id": "usr-sharma-cardio",
        "doctor_name": "Dr. Priya Sharma, MD",
        "department": "Cardiology",
        "specialty": "Cardiology",
        "room_bed": "Ward 4A · Bed 06",
        "admission_status": "Inpatient Active",
    },
    "PAT-013": {
        "doctor_id": "usr-patel-im",
        "doctor_name": "Dr. Anita Patel, MD",
        "department": "Internal Medicine",
        "specialty": "Internal Medicine",
        "room_bed": "Ward 2A · Bed 22",
        "admission_status": "Inpatient Active",
    },
    "PAT-014": {
        "doctor_id": "usr-patel-im",
        "doctor_name": "Dr. Anita Patel, MD",
        "department": "Internal Medicine",
        "specialty": "Internal Medicine",
        "room_bed": "Ward 2B · Bed 11",
        "admission_status": "Inpatient Active",
    },
    "PAT-015": {
        "doctor_id": "usr-sharma-cardio",
        "doctor_name": "Dr. Priya Sharma, MD",
        "department": "Cardiology",
        "specialty": "Cardiology",
        "room_bed": "Ward 3B · Bed 15",
        "admission_status": "Inpatient Active",
    },
}


def _resolve_patients_file() -> Path:
    raw = os.environ.get("PATIENTS_DB")
    candidates: list[Path] = []
    if raw:
        p = Path(raw)
        if p.is_file():
            return p.resolve()
        candidates.extend([
            PROJECT_ROOT / p,
            BACKEND_DIR / p,
            PROJECT_ROOT / "data" / p.name,
            BACKEND_DIR / "data" / p.name,
        ])
    candidates.extend([
        BACKEND_DIR / "data" / "patients.sample.json",
        PROJECT_ROOT / "data" / "patients.sample.json",
        PROJECT_ROOT / "data" / "patients.json",
    ])
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return (BACKEND_DIR / "data" / "patients.sample.json").resolve()


def _ensure_patients_loaded() -> dict[str, dict[str, Any]]:
    records = store.list_all()
    if not records:
        candidates = [
            BACKEND_DIR / "data" / "patients.sample.json",
            PROJECT_ROOT / "data" / "patients.sample.json",
            PROJECT_ROOT / "data" / "patients.json",
        ]
        for c in candidates:
            if c.is_file():
                try:
                    data = json.loads(c.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        data = {str(r.get("patient_id") or r.get("id")): r for r in data if isinstance(r, dict)}
                    if isinstance(data, dict) and data:
                        store.path = c.resolve()
                        with store._lock:
                            store._records = data
                            store.error = ""
                        records = store.list_all()
                        break
                except Exception as e:
                    log.warning(f"Failed to read patient file {c}: {e}")
    return records


PATIENTS_PATH = _resolve_patients_file()
store = PatientStore(PATIENTS_PATH)
_ensure_patients_loaded()
agent = MedAgent(deps=AgentDeps(patients=store))

app = FastAPI(
    title="MedPerplexity Hospital Clinical Intelligence Platform",
    version="1.0.0",
    description="Hospital-licensed clinical intelligence, evidence discovery, and safety verification platform.",
)

# CORS configuration
raw_origins = os.environ.get(
    "MEDPERPLEXITY_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
)
allowed_origins = [item.strip() for item in raw_origins.split(",") if item.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Request & Response Schemas
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(default="web-demo", min_length=1, max_length=100)


class SavePaperRequest(BaseModel):
    pmid: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authors: str = Field(default="")
    journal: str = Field(default="")
    pub_date: str = Field(default="")
    abstract: str = Field(default="")
    doi: Optional[str] = None
    url: Optional[str] = None
    evidence_type: str = Field(default="journal_article")
    specialty: str = Field(default="General Medicine")
    notes: Optional[str] = None


class UserPreferencesUpdate(BaseModel):
    specialty: Optional[str] = None
    secondary_specialties: Optional[List[str]] = None
    preferred_date_range: Optional[str] = None
    theme: Optional[str] = None


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2)
    designation: str = Field(min_length=2)
    department: str = Field(min_length=2)
    role: str = Field(pattern="^(doctor|hospital_admin)$")
    specialty: Optional[str] = "General Medicine"


class UpdateUserStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|suspended)$")


# --------------------------------------------------------------------------- #
# Health & Status
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "medperplexity-hospital-platform",
        "engine": "MedPerplexity v0.1.0",
        "database": "sqlite3_active",
        "time": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- #
# Authentication & Hospital Session
# --------------------------------------------------------------------------- #
@app.post("/api/auth/login")
def login(request: LoginRequest) -> dict[str, Any]:
    user = authenticate_user(request.email, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password for this hospital domain.",
        )

    token = create_session(user["id"])
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Record audit event
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"aud-{uuid.uuid4().hex[:10]}",
                user["organization_id"],
                user["id"],
                "auth_login",
                "session",
                user["id"],
                json.dumps({"email": user["email"], "role": user["role"]}),
                now_iso,
            ),
        )

    secondary = []
    if user.get("secondary_specialties_json"):
        try:
            secondary = json.loads(user["secondary_specialties_json"])
        except Exception:
            secondary = []

    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "designation": user["designation"],
            "department": user["department"],
            "role": user["role"],
            "avatar_initials": user["avatar_initials"],
            "specialty": user.get("specialty") or "Cardiology",
            "secondary_specialties": secondary,
            "theme": user.get("theme") or "light",
            "organization": {
                "id": user["organization_id"],
                "name": user["org_name"],
                "code": user["org_code"],
                "tier": user["org_tier"],
            },
        },
    }


@app.get("/api/auth/me")
def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "designation": user["designation"],
            "department": user["department"],
            "role": user["role"],
            "avatar_initials": user["avatar_initials"],
            "specialty": user.get("specialty") or "Cardiology",
            "secondary_specialties": user.get("secondary_specialties", []),
            "preferred_date_range": user.get("preferred_date_range", "2018-present"),
            "theme": user.get("theme") or "light",
            "organization": {
                "id": user["organization_id"],
                "name": user["org_name"],
                "code": user["org_code"],
                "tier": user["org_tier"],
                "entitlements": user.get("entitlements", {}),
            },
        }
    }


@app.post("/api/auth/logout")
def logout(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    # Invalidation happens per token
    return {"status": "logged_out"}


@app.patch("/api/auth/preferences")
def update_preferences(
    prefs: UserPreferencesUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db_connection() as conn:
        current = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user["id"],)
        ).fetchone()

        new_specialty = prefs.specialty if prefs.specialty is not None else (current["specialty"] if current else "Cardiology")
        new_secondary = json.dumps(prefs.secondary_specialties) if prefs.secondary_specialties is not None else (current["secondary_specialties_json"] if current else "[]")
        new_range = prefs.preferred_date_range if prefs.preferred_date_range is not None else (current["preferred_date_range"] if current else "2018-present")
        new_theme = prefs.theme if prefs.theme is not None else (current["theme"] if current else "light")

        conn.execute(
            """INSERT OR REPLACE INTO user_preferences (user_id, specialty, secondary_specialties_json, default_topics_json, preferred_date_range, theme, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], new_specialty, new_secondary, json.dumps([]), new_range, new_theme, now_iso),
        )

    return {
        "status": "updated",
        "preferences": {
            "specialty": new_specialty,
            "secondary_specialties": json.loads(new_secondary),
            "preferred_date_range": new_range,
            "theme": new_theme,
        },
    }


# --------------------------------------------------------------------------- #
# Patient Workspace & Clinical Decision Support
# --------------------------------------------------------------------------- #
def _patient_or_404(patient_id: str) -> dict[str, Any]:
    _ensure_patients_loaded()
    patient = store.get(patient_id)
    if patient is None:
        raise HTTPException(
            status_code=404,
            detail=f"Patient '{patient_id}' was not found in the configured patient file.",
        )
    return patient


def _patient_summary(patient_id: str, patient: dict[str, Any]) -> dict[str, Any]:
    assignment = PATIENT_DOCTOR_ASSIGNMENTS.get(patient_id, {
        "doctor_id": "usr-sharma-cardio",
        "doctor_name": "Dr. Priya Sharma, MD",
        "department": "Cardiology",
        "specialty": "Cardiology",
        "room_bed": "Ward 3B · Bed 01",
        "admission_status": "Inpatient Active",
    })
    return {
        "name": patient.get("name") or patient.get("full_name") or "Unnamed patient",
        "age": patient.get("age"),
        "sex": patient.get("sex"),
        "conditions": patient.get("condition_tags", []),
        "allergies": patient.get("allergies", []),
        "current_medications": patient.get("current_medications", []),
        "assigned_doctor_id": assignment["doctor_id"],
        "assigned_doctor_name": assignment["doctor_name"],
        "department": assignment["department"],
        "specialty": assignment["specialty"],
        "room_bed": assignment["room_bed"],
        "admission_status": assignment["admission_status"],
    }


@app.get("/api/patients")
def list_patients(
    doctor_id: Optional[str] = Query(None, description="Filter by assigned doctor ID"),
    department: Optional[str] = Query(None, description="Filter by department name"),
) -> dict[str, Any]:
    """List configured patients for the clinical workspace."""
    patient_records = _ensure_patients_loaded()

    doc_filter = doctor_id if isinstance(doctor_id, str) and doctor_id.strip() else None
    dept_filter = department if isinstance(department, str) and department.strip() else None

    records = []
    for patient_id, patient in sorted(patient_records.items()):
        summary = _patient_summary(patient_id, patient)
        if doc_filter and summary["assigned_doctor_id"] != doc_filter:
            continue
        if dept_filter and summary["department"].lower() != dept_filter.lower():
            continue
        records.append({
            "patient_id": patient_id,
            **summary,
        })

    return {
        "items": records,
        "count": len(records),
        "source": "configured_patient_file",
        "synthetic_demo": True,
    }


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str) -> dict[str, Any]:
    patient = _patient_or_404(patient_id)
    return {
        "patient_id": patient_id,
        **_patient_summary(patient_id, patient),
        "observations": [],
        "encounters": [],
        "prescription_history": [],
        "data_availability": {
            "observations": "not_configured",
            "encounters": "not_configured",
            "prescription_history": "not_configured",
        },
        "record_source": "synthetic_sample",
    }


@app.get("/api/patients/{patient_id}/trends")
def get_patient_trends(patient_id: str) -> dict[str, Any]:
    _patient_or_404(patient_id)
    return {
        "patient_id": patient_id,
        "series": [],
        "message": "No observation series are configured for this synthetic record.",
    }


@app.post("/api/patients/{patient_id}/chat")
def chat(
    patient_id: str,
    request: ChatRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Execute the MedPerplexity clinical decision-support agent against the real engine."""
    _patient_or_404(patient_id)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        thread_key = f"{user['id']}:{patient_id}:{request.thread_id}"

        # If the incoming message is a fresh clinical question or preset prompt,
        # clear any stale pending task so the user is never stuck in a clarification loop
        msg_clean = request.message.strip().lower()
        is_fresh = any(msg_clean.startswith(p) for p in (
            "can i", "prescribe", "check", "evaluate", "find", "what", "is ", "how ", "should i", "could i", "give "
        )) or len(msg_clean.split()) >= 5
        if is_fresh:
            try:
                with agent.session_store._connect() as s_conn:
                    s_conn.execute("UPDATE conversations SET pending_task_json=NULL WHERE conversation_id=?", (thread_key,))
                    s_conn.commit()
            except Exception:
                pass
            with agent._lock_for(thread_key):
                if thread_key in agent._sessions:
                    agent._sessions[thread_key]["pending_task"] = None

        # Delegate directly to the real MedAgent package
        result = agent.ask(patient_id, request.message, thread_id=thread_key)

        # Persist assessment to SQLite clinical_assessments table
        assessment_id = f"asm-{uuid.uuid4().hex[:12]}"
        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO clinical_assessments (
                    id, organization_id, user_id, patient_id, thread_id, query,
                    status, title, message, structured_response_json, audit_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id,
                    user["organization_id"],
                    user["id"],
                    patient_id,
                    request.thread_id,
                    request.message,
                    result.get("status", "caution"),
                    result.get("title", "Clinical Assessment"),
                    result.get("message", ""),
                    json.dumps(result),
                    json.dumps(result.get("audit") or {}),
                    now_iso,
                ),
            )

            # Record audit event
            conn.execute(
                """INSERT INTO audit_events (
                    id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"aud-{uuid.uuid4().hex[:10]}",
                    user["organization_id"],
                    user["id"],
                    "clinical_assessment",
                    "patient",
                    patient_id,
                    json.dumps({
                        "assessment_id": assessment_id,
                        "query": request.message[:80],
                        "status": result.get("status"),
                        "flags_count": len(result.get("flags") or []),
                    }),
                    now_iso,
                ),
            )

        return {
            "patient_id": patient_id,
            "response": result,
            "assessment_id": assessment_id,
            "persistence": "sqlite3_persisted",
        }
    except Exception as exc:
        log.exception("Clinical agent failed on query: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"The clinical agent could not complete the request ({type(exc).__name__}: {str(exc)}).",
        ) from exc


@app.post("/api/patients/{patient_id}/chat/reset")
def reset_chat(
    patient_id: str,
    request: ChatRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    _patient_or_404(patient_id)
    thread_key = f"{user['id']}:{patient_id}:{request.thread_id}"
    agent.reset(thread_id=thread_key)
    try:
        with agent.session_store._connect() as s_conn:
            s_conn.execute("DELETE FROM conversations WHERE conversation_id=?", (thread_key,))
            s_conn.execute("DELETE FROM conversation_messages WHERE conversation_id=?", (thread_key,))
            s_conn.commit()
    except Exception as e:
        log.warning("Could not delete persistent session: %s", e)
    return {"status": "reset", "patient_id": patient_id}


# --------------------------------------------------------------------------- #
# Independent Research Library
# --------------------------------------------------------------------------- #
@app.get("/api/research")
def search_research(
    query: Optional[str] = Query(None, description="Keywords, drug name, condition, or author"),
    specialty: Optional[str] = Query(None, description="Clinical specialty filter"),
    publication_type: Optional[str] = Query(None, description="Publication type filter"),
    min_year: int = Query(2018, ge=1990, le=2026),
    limit: int = Query(10, ge=1, le=50),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Independent medical research discovery: PubMed search with specialty filters."""
    # If no specialty is explicitly provided, default to authenticated doctor's specialty
    eff_specialty = specialty or user.get("specialty") or "All Specialties"

    return search_research_papers(
        query=query,
        specialty=eff_specialty,
        publication_type=publication_type,
        min_year=min_year,
        limit=limit,
    )


@app.get("/api/research/saved")
def list_saved_papers(
    specialty: Optional[str] = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    papers = get_saved_papers(user["id"], specialty=specialty)
    return {"items": papers, "count": len(papers)}


@app.post("/api/research/saved")
def add_saved_paper(
    req: SavePaperRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    res = save_paper(user["id"], user["organization_id"], req.model_dump(), notes=req.notes)

    # Record audit event
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"aud-{uuid.uuid4().hex[:10]}",
                user["organization_id"],
                user["id"],
                "research_saved",
                "paper",
                req.pmid,
                json.dumps({"title": req.title[:60], "specialty": req.specialty}),
                now_iso,
            ),
        )

    return res


@app.delete("/api/research/saved/{pmid}")
def remove_paper(
    pmid: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    success = remove_saved_paper(user["id"], pmid)
    if not success:
        raise HTTPException(status_code=404, detail="Paper not found in saved items.")
    return {"status": "removed", "pmid": pmid}


@app.get("/api/research/{pmid}")
def get_single_paper(
    pmid: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    paper = get_paper_details(pmid)
    if not paper:
        raise HTTPException(status_code=404, detail=f"PubMed record {pmid} not found.")
    return paper


# --------------------------------------------------------------------------- #
# Clinical Assessments History
# --------------------------------------------------------------------------- #
@app.get("/api/assessments")
def get_assessments(
    patient_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve persisted past clinical assessments for the authenticated doctor."""
    with get_db_connection() as conn:
        query = "SELECT * FROM clinical_assessments WHERE organization_id = ?"
        params: List[Any] = [user["organization_id"]]

        # Non-admins only see their own assessments
        if user["role"] != "hospital_admin":
            query += " AND user_id = ?"
            params.append(user["id"])

        if patient_id:
            query += " AND patient_id = ?"
            params.append(patient_id)

        if status_filter and status_filter.lower() != "all":
            query += " AND status = ?"
            params.append(status_filter.lower())

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        assessments = []
        for r in rows:
            data = dict(r)
            try:
                data["structured_response"] = json.loads(data["structured_response_json"])
            except Exception:
                data["structured_response"] = {}
            assessments.append(data)

        return {"items": assessments, "count": len(assessments)}


@app.get("/api/assessments/{assessment_id}")
def get_assessment_detail(
    assessment_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM clinical_assessments WHERE id = ? AND organization_id = ?",
            (assessment_id, user["organization_id"]),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        data = dict(row)
        data["structured_response"] = json.loads(data["structured_response_json"])
        data["audit"] = json.loads(data["audit_json"] or "{}")
        return data


# --------------------------------------------------------------------------- #
# Audit Log Viewer
# --------------------------------------------------------------------------- #
@app.get("/api/audit")
def get_audit_trail(
    event_type: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve hospital audit events."""
    with get_db_connection() as conn:
        query = "SELECT a.*, u.full_name as user_name, u.email as user_email, u.role as user_role FROM audit_events a JOIN users u ON a.user_id = u.id WHERE a.organization_id = ?"
        params: List[Any] = [user["organization_id"]]

        # Doctors see their own actions; admins see full hospital audit trail
        if user["role"] != "hospital_admin":
            query += " AND a.user_id = ?"
            params.append(user["id"])

        if event_type:
            query += " AND a.event_type = ?"
            params.append(event_type)

        query += " ORDER BY a.timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        events = []
        for r in rows:
            it = dict(r)
            try:
                it["details"] = json.loads(it["details_json"])
            except Exception:
                it["details"] = {}
            events.append(it)

        return {"items": events, "count": len(events)}


# --------------------------------------------------------------------------- #
# Medication Catalog Search
# --------------------------------------------------------------------------- #
@app.get("/api/medications/search")
def search_medications(
    q: str = Query(..., min_length=2, description="Medicine name or active ingredient"),
    limit: int = Query(10, ge=1, le=50),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Search Jan Aushadhi generic catalog and brand prices from bundled database."""
    search_term = f"%{q.strip()}%"
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM medications_catalog
               WHERE generic_name LIKE ? OR common_brands_json LIKE ?
               LIMIT ?""",
            (search_term, search_term, limit),
        ).fetchall()

        items = []
        for r in rows:
            it = dict(r)
            try:
                it["common_brands"] = json.loads(it["common_brands_json"] or "[]")
            except Exception:
                it["common_brands"] = []
            items.append(it)

        return {
            "query": q,
            "count": len(items),
            "source": "jan_aushadhi_catalog",
            "items": items,
        }


# --------------------------------------------------------------------------- #
# Hospital Administration (Role: hospital_admin)
# --------------------------------------------------------------------------- #
@app.get("/api/admin/organization")
def get_organization_info(
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        org = conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (user["organization_id"],)
        ).fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        total_users = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE organization_id = ?",
            (user["organization_id"],),
        ).fetchone()["cnt"]

        total_assessments = conn.execute(
            "SELECT COUNT(*) as cnt FROM clinical_assessments WHERE organization_id = ?",
            (user["organization_id"],),
        ).fetchone()["cnt"]

        return {
            "id": org["id"],
            "name": org["name"],
            "code": org["code"],
            "tier": org["tier"],
            "status": org["status"],
            "entitlements": json.loads(org["entitlements_json"]),
            "stats": {
                "active_seats": total_users,
                "total_assessments": total_assessments,
            },
            "created_at": org["created_at"],
        }


@app.get("/api/admin/users")
def list_hospital_users(
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.full_name, u.designation, u.department, u.role, u.status, u.avatar_initials, u.created_at,
                      p.specialty
               FROM users u
               LEFT JOIN user_preferences p ON u.id = p.user_id
               WHERE u.organization_id = ?
               ORDER BY u.created_at ASC""",
            (user["organization_id"],),
        ).fetchall()

        return {"items": [dict(r) for r in rows], "count": len(rows)}


@app.post("/api/admin/users")
def invite_user(
    req: CreateUserRequest,
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    user_id = f"usr-{uuid.uuid4().hex[:10]}"
    pwd_hash, salt = hash_password(req.password)

    # Initials from full name
    initials = "".join([part[0].upper() for part in req.full_name.split() if part])[:2] or "DR"

    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (req.email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="A user with this email already exists.")

        conn.execute(
            """INSERT INTO users (id, organization_id, email, password_hash, salt, full_name, designation, department, role, status, avatar_initials, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (user_id, user["organization_id"], req.email, pwd_hash, salt, req.full_name, req.designation, req.department, req.role, initials, now_iso),
        )

        conn.execute(
            """INSERT INTO user_preferences (user_id, specialty, secondary_specialties_json, default_topics_json, preferred_date_range, theme, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, req.specialty or "General Medicine", json.dumps([]), json.dumps([]), "2018-present", "light", now_iso),
        )

        # Audit event
        conn.execute(
            """INSERT INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"aud-{uuid.uuid4().hex[:10]}",
                user["organization_id"],
                user["id"],
                "user_created",
                "user",
                user_id,
                json.dumps({"email": req.email, "role": req.role, "designation": req.designation}),
                now_iso,
            ),
        )

    return {
        "status": "created",
        "user_id": user_id,
        "email": req.email,
        "full_name": req.full_name,
    }


@app.patch("/api/admin/users/{user_id}/status")
def toggle_user_status(
    user_id: str,
    req: UpdateUserStatusRequest,
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        target = conn.execute(
            "SELECT id, email, role FROM users WHERE id = ? AND organization_id = ?",
            (user_id, user["organization_id"]),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="User not found.")

        if target["id"] == user["id"]:
            raise HTTPException(status_code=400, detail="Administrators cannot modify their own status.")

        conn.execute(
            "UPDATE users SET status = ? WHERE id = ?", (req.status, user_id)
        )

        # Record audit
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """INSERT INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"aud-{uuid.uuid4().hex[:10]}",
                user["organization_id"],
                user["id"],
                "user_status_changed",
                "user",
                user_id,
                json.dumps({"target_email": target["email"], "new_status": req.status}),
                now_iso,
            ),
        )

    return {"status": "updated", "user_id": user_id, "new_status": req.status}

# --------------------------------------------------------------------------- #
# Independent Research Library
# --------------------------------------------------------------------------- #
@app.get("/api/research")
def search_research(
    query: Optional[str] = Query(None, description="Keywords, drug name, condition, or author"),
    specialty: Optional[str] = Query(None, description="Clinical specialty filter"),
    publication_type: Optional[str] = Query(None, description="Publication type filter"),
    min_year: int = Query(2018, ge=1990, le=2026),
    limit: int = Query(10, ge=1, le=50),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Independent medical research discovery: PubMed search with specialty filters."""
    # If no specialty is explicitly provided, default to authenticated doctor's specialty
    eff_specialty = specialty or user.get("specialty") or "All Specialties"

    return search_research_papers(
        query=query,
        specialty=eff_specialty,
        publication_type=publication_type,
        min_year=min_year,
        limit=limit,
    )


@app.get("/api/research/saved")
def list_saved_papers(
    specialty: Optional[str] = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    papers = get_saved_papers(user["id"], specialty=specialty)
    return {"items": papers, "count": len(papers)}


@app.post("/api/research/saved")
def add_saved_paper(
    req: SavePaperRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    res = save_paper(user["id"], user["organization_id"], req.model_dump(), notes=req.notes)

    # Record audit event
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"aud-{uuid.uuid4().hex[:10]}",
                user["organization_id"],
                user["id"],
                "research_saved",
                "paper",
                req.pmid,
                json.dumps({"title": req.title[:60], "specialty": req.specialty}),
                now_iso,
            ),
        )

    return res


@app.delete("/api/research/saved/{pmid}")
def remove_paper(
    pmid: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    success = remove_saved_paper(user["id"], pmid)
    if not success:
        raise HTTPException(status_code=404, detail="Paper not found in saved items.")
    return {"status": "removed", "pmid": pmid}


@app.get("/api/research/{pmid}")
def get_single_paper(
    pmid: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    paper = get_paper_details(pmid)
    if not paper:
        raise HTTPException(status_code=404, detail=f"PubMed record {pmid} not found.")
    return paper


# --------------------------------------------------------------------------- #
# Clinical Assessments History
# --------------------------------------------------------------------------- #
@app.get("/api/assessments")
def get_assessments(
    patient_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve persisted past clinical assessments for the authenticated doctor."""
    with get_db_connection() as conn:
        query = "SELECT * FROM clinical_assessments WHERE organization_id = ?"
        params: List[Any] = [user["organization_id"]]

        # Non-admins only see their own assessments
        if user["role"] != "hospital_admin":
            query += " AND user_id = ?"
            params.append(user["id"])

        if patient_id:
            query += " AND patient_id = ?"
            params.append(patient_id)

        if status_filter and status_filter.lower() != "all":
            query += " AND status = ?"
            params.append(status_filter.lower())

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        assessments = []
        for r in rows:
            data = dict(r)
            try:
                data["structured_response"] = json.loads(data["structured_response_json"])
            except Exception:
                data["structured_response"] = {}
            assessments.append(data)

        return {"items": assessments, "count": len(assessments)}


@app.get("/api/assessments/{assessment_id}")
def get_assessment_detail(
    assessment_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM clinical_assessments WHERE id = ? AND organization_id = ?",
            (assessment_id, user["organization_id"]),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        data = dict(row)
        data["structured_response"] = json.loads(data["structured_response_json"])
        data["audit"] = json.loads(data["audit_json"] or "{}")
        return data


# --------------------------------------------------------------------------- #
# Audit Log Viewer
# --------------------------------------------------------------------------- #
@app.get("/api/audit")
def get_audit_trail(
    event_type: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve hospital audit events."""
    with get_db_connection() as conn:
        query = "SELECT a.*, u.full_name as user_name, u.email as user_email, u.role as user_role FROM audit_events a JOIN users u ON a.user_id = u.id WHERE a.organization_id = ?"
        params: List[Any] = [user["organization_id"]]

        # Doctors see their own actions; admins see full hospital audit trail
        if user["role"] != "hospital_admin":
            query += " AND a.user_id = ?"
            params.append(user["id"])

        if event_type:
            query += " AND a.event_type = ?"
            params.append(event_type)

        query += " ORDER BY a.timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        events = []
        for r in rows:
            it = dict(r)
            try:
                it["details"] = json.loads(it["details_json"])
            except Exception:
                it["details"] = {}
            events.append(it)

        return {"items": events, "count": len(events)}


# --------------------------------------------------------------------------- #
# Medication Catalog Search
# --------------------------------------------------------------------------- #
@app.get("/api/medications/search")
def search_medications(
    q: str = Query(..., min_length=2, description="Medicine name or active ingredient"),
    limit: int = Query(10, ge=1, le=50),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Search Jan Aushadhi generic catalog and brand prices from bundled database."""
    search_term = f"%{q.strip()}%"
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM medications_catalog
               WHERE generic_name LIKE ? OR common_brands_json LIKE ?
               LIMIT ?""",
            (search_term, search_term, limit),
        ).fetchall()

        items = []
        for r in rows:
            it = dict(r)
            try:
                it["common_brands"] = json.loads(it["common_brands_json"] or "[]")
            except Exception:
                it["common_brands"] = []
            items.append(it)

        return {
            "query": q,
            "count": len(items),
            "source": "jan_aushadhi_catalog",
            "items": items,
        }


# --------------------------------------------------------------------------- #
# Hospital Administration (Role: hospital_admin)
# --------------------------------------------------------------------------- #
@app.get("/api/admin/organization")
def get_organization_info(
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        org = conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (user["organization_id"],)
        ).fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        total_users = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE organization_id = ?",
            (user["organization_id"],),
        ).fetchone()["cnt"]

        total_assessments = conn.execute(
            "SELECT COUNT(*) as cnt FROM clinical_assessments WHERE organization_id = ?",
            (user["organization_id"],),
        ).fetchone()["cnt"]

        return {
            "id": org["id"],
            "name": org["name"],
            "code": org["code"],
            "tier": org["tier"],
            "status": org["status"],
            "entitlements": json.loads(org["entitlements_json"]),
            "stats": {
                "active_seats": total_users,
                "total_assessments": total_assessments,
            },
            "created_at": org["created_at"],
        }


@app.get("/api/admin/users")
def list_hospital_users(
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.full_name, u.designation, u.department, u.role, u.status, u.avatar_initials, u.created_at,
                      p.specialty
               FROM users u
               LEFT JOIN user_preferences p ON u.id = p.user_id
               WHERE u.organization_id = ?
               ORDER BY u.created_at ASC""",
            (user["organization_id"],),
        ).fetchall()

        return {"items": [dict(r) for r in rows], "count": len(rows)}


@app.post("/api/admin/users")
def invite_user(
    req: CreateUserRequest,
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    user_id = f"usr-{uuid.uuid4().hex[:10]}"
    pwd_hash, salt = hash_password(req.password)

    # Initials from full name
    initials = "".join([part[0].upper() for part in req.full_name.split() if part])[:2] or "DR"

    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (req.email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="A user with this email already exists.")

        conn.execute(
            """INSERT INTO users (id, organization_id, email, password_hash, salt, full_name, designation, department, role, status, avatar_initials, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (user_id, user["organization_id"], req.email, pwd_hash, salt, req.full_name, req.designation, req.department, req.role, initials, now_iso),
        )

        conn.execute(
            """INSERT INTO user_preferences (user_id, specialty, secondary_specialties_json, default_topics_json, preferred_date_range, theme, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, req.specialty or "General Medicine", json.dumps([]), json.dumps([]), "2018-present", "light", now_iso),
        )

        # Audit event
        conn.execute(
            """INSERT INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"aud-{uuid.uuid4().hex[:10]}",
                user["organization_id"],
                user["id"],
                "user_created",
                "user",
                user_id,
                json.dumps({"email": req.email, "role": req.role, "designation": req.designation}),
                now_iso,
            ),
        )

    return {
        "status": "created",
        "user_id": user_id,
        "email": req.email,
        "full_name": req.full_name,
    }


@app.patch("/api/admin/users/{user_id}/status")
def toggle_user_status(
    user_id: str,
    req: UpdateUserStatusRequest,
    user: dict[str, Any] = Depends(require_role("hospital_admin")),
) -> dict[str, Any]:
    with get_db_connection() as conn:
        target = conn.execute(
            "SELECT id, email, role FROM users WHERE id = ? AND organization_id = ?",
            (user_id, user["organization_id"]),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="User not found.")

        if target["id"] == user["id"]:
            raise HTTPException(status_code=400, detail="Administrators cannot modify their own status.")

        conn.execute(
            "UPDATE users SET status = ? WHERE id = ?", (req.status, user_id)
        )

        # Record audit
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """INSERT INTO audit_events (id, organization_id, user_id, event_type, resource_type, resource_id, details_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"aud-{uuid.uuid4().hex[:10]}",
                user["organization_id"],
                user["id"],
                "user_status_changed",
                "user",
                user_id,
                json.dumps({"target_email": target["email"], "new_status": req.status}),
                now_iso,
            ),
        )

    return {"status": "updated", "user_id": user_id, "new_status": req.status}

