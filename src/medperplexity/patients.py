
"""Patient records: loading, lookup, and privacy-minimised views."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .config import DATA_DIR, PROJECT_ROOT

def _default_patients_path() -> Path:
    raw = os.environ.get("PATIENTS_DB")
    if raw:
        p = Path(raw)
        if p.is_file():
            return p.resolve()
        for candidate in (
            PROJECT_ROOT / p,
            DATA_DIR / p.name,
            PROJECT_ROOT / "data" / p.name,
            PROJECT_ROOT / "backend" / "app" / "data" / p.name,
        ):
            if candidate.is_file():
                return candidate.resolve()
        return p

    for candidate in (
        DATA_DIR / "patients.json",
        PROJECT_ROOT / "data" / "patients.json",
        DATA_DIR / "patients.sample.json",
        PROJECT_ROOT / "data" / "patients.sample.json",
        PROJECT_ROOT / "backend" / "app" / "data" / "patients.sample.json",
    ):
        if candidate.is_file():
            return candidate.resolve()

    return (DATA_DIR / "patients.json").resolve()


DEFAULT_PATIENTS_PATH = _default_patients_path()

# Fields that identify a person. They never go into an LLM prompt or PubMed query.
IDENTIFYING_KEYS = frozenset("""
    name full_name first_name last_name patient_name id patient_id mrn uhid
    abha aadhaar aadhar phone mobile contact email address city pincode zip
    guardian emergency_contact dob date_of_birth
""".split())

_MAX_FIELD_CHARS = 400


class PatientStore:
    """JSON-backed patient lookup that reloads automatically when the file changes.

    Supported file formats:
      - {"PAT-001": {...}, "PAT-002": {...}}
      - [{"patient_id": "PAT-001", ...}, {"id": "PAT-002", ...}]
    """

    def __init__(self, path: Optional[str | Path] = None):
        self._custom_path = path is not None
        self.path = Path(path) if path else _default_patients_path()
        self._lock = threading.Lock()
        self._mtime: Optional[float] = None
        self._records: Dict[str, Dict[str, Any]] = {}
        self.error: str = ""

    def _load(self) -> None:
        if not self.path.is_file():
            if not self._custom_path:
                candidates = [
                    PROJECT_ROOT / self.path,
                    DATA_DIR / self.path.name,
                    PROJECT_ROOT / "data" / self.path.name,
                    PROJECT_ROOT / "backend" / "app" / "data" / self.path.name,
                    DATA_DIR / "patients.sample.json",
                    PROJECT_ROOT / "data" / "patients.sample.json",
                    PROJECT_ROOT / "backend" / "app" / "data" / "patients.sample.json",
                ]
                for c in candidates:
                    if c.is_file():
                        self.path = c
                        break
            else:
                for candidate in (PROJECT_ROOT / self.path, DATA_DIR / self.path.name):
                    if candidate.is_file():
                        self.path = candidate
                        break

        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._records = {}
            self._mtime = None
            self.error = f"patient file not found: {self.path}"
            return

        if mtime == self._mtime:
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._records = {}
            self._mtime = mtime
            self.error = (
                f"patient file unreadable: {type(exc).__name__}"
            )
            return

        if isinstance(data, list):
            data = {
                str(record.get("patient_id") or record.get("id")): record
                for record in data
                if isinstance(record, dict)
                and (record.get("patient_id") or record.get("id"))
            }

        self._records = (
            {
                str(patient_id): record
                for patient_id, record in data.items()
                if isinstance(record, dict)
            }
            if isinstance(data, dict)
            else {}
        )

        self._mtime = mtime
        self.error = ""

    def get(self, patient_id: str) -> Optional[Dict[str, Any]]:
        """Return a copy of one patient record, or None if it does not exist."""
        with self._lock:
            self._load()
            record = self._records.get(str(patient_id))
            return dict(record) if record is not None else None

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """Return copies of all configured patient records, keyed by patient ID."""
        with self._lock:
            self._load()
            return {
                patient_id: dict(record)
                for patient_id, record in self._records.items()
            }


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
