"""Configuration: paths and NCBI credentials (read from the environment, never hardcoded)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MEDPERPLEXITY_DATA_DIR", PROJECT_ROOT / "data"))
DEFAULT_DB_PATH = Path(os.environ.get("MEDPERPLEXITY_DB", DATA_DIR / "medicines.json"))
DEFAULT_TOOL_NAME = "MedPerplexity"


def _load_env_file(path: Path) -> None:
    """Tiny .env loader (KEY=VALUE lines). Real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(PROJECT_ROOT / ".env")


def request_delay() -> float:
    """Seconds to wait between NCBI requests (3 req/s without a key, 10 with one)."""
    return 0.11 if os.environ.get("NCBI_API_KEY") else 0.34


def configure_entrez(entrez: Any = None) -> Any:
    """Apply NCBI identification settings to ``Bio.Entrez`` and return it."""
    if entrez is None:
        try:
            from Bio import Entrez as entrez  # lazy import so non-PubMed features work without Biopython
        except ImportError as exc:
            raise ImportError("Biopython is required for PubMed features: pip install biopython") from exc

    email = os.environ.get("NCBI_EMAIL")
    if email:
        entrez.email = email
    else:
        log.warning("NCBI_EMAIL is not set; NCBI asks clients to identify themselves (see .env.example).")

    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        entrez.api_key = api_key

    entrez.tool = os.environ.get("NCBI_TOOL", DEFAULT_TOOL_NAME)
    return entrez
