"""Patient records: loading, and a privacy-minimised view that is safe to send to an LLM."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .config import DATA_DIR

DEFAULT_PATIENTS_PATH = Path(os.environ.get("PATIENTS_DB", DATA_DIR / "patients.json"))

# Fields that identify a person. They never go into an LLM prompt or a PubMed query.
IDENTIFYING_KEYS = frozenset("""
    name full_name first_name last_name patient_name id patient_id mrn uhid abha aadhaar aadhar phone mobile
    contact email address city pincode zip guardian emergency_contact dob date_of_birth
""".split())
_MAX_FIELD_CHARS = 400


class PatientStore:
    """JSON-backed patient lookup that reloads automatically when the file changes.

    The file may be ``{"PAT-001": {...}, ...}`` or a list of records carrying an ``id`` / ``patient_id``.
    """

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else DEFAULT_PATIENTS_PATH
        self._lock = threading.Lock()
        self._mtime: Optional[float] = None
        self._records: Dict[str, Dict[str, Any]] = {}
        self.error: str = ""

    def _load(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._records, self._mtime, self.error = {}, None, f"patient file not found: {self.path}"
            return
        if mtime == self._mtime:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._records, self._mtime, self.error = {}, mtime, f"patient file unreadable: {type(exc).__name__}"
            return
        if isinstance(data, list):
            data = {str(r.get("patient_id") or r.get("id")): r for r in data if isinstance(r, dict)}
        self._records = {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
        self._mtime, self.error = mtime, ""

    def get(self, patient_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._load()
            record = self._records.get(str(patient_id))
            return dict(record) if record is not None else None


def patient_view(patient: Dict[str, Any]) -> Dict[str, Any]:
    """Clinical fields only: identifying keys removed, long text truncated."""
    view: Dict[str, Any] = {}
    for key, value in (patient or {}).items():
        if str(key).lower() in IDENTIFYING_KEYS:
            continue
        if isinstance(value, str):
            value = value[:_MAX_FIELD_CHARS]
        view[key] = value
    return view
