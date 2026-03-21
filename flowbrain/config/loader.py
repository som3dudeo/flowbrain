"""
Config loader — the FIRST thing that runs.

Loads .env, validates values, and provides a single Config object
that all other modules import. This fixes the critical dotenv load
order bug where PORT was read before .env was loaded.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

# Load dotenv IMMEDIATELY — before any os.getenv calls
try:
    from dotenv import load_dotenv
    # Walk up to find .env relative to the project root
    _project_root = Path(__file__).resolve().parent.parent.parent
    _env_file = _project_root / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
    else:
        load_dotenv()  # try CWD
except ImportError:
    pass


@dataclass(frozen=True)
class Config:
    """Immutable configuration loaded once at startup."""

    # Server
    host: str = "127.0.0.1"  # localhost only by default (SECURITY)
    port: int = 8001          # default 8001, NOT 8000

    # URLs
    flow_finder_url: str = "http://127.0.0.1:8001"  # legacy field name; FLOWBRAIN_URL is preferred in env/docs
    n8n_base_url: str = "http://localhost:5678"
    n8n_default_webhook: str = ""

    # Safety
    min_autoexec_confidence: float = 0.85
    min_preview_confidence: float = 0.40
    min_search_confidence: float = 0.30
    default_auto_execute: bool = False  # preview by default

    # Ollama
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # Paths
    project_root: str = ""
    data_dir: str = ""
    db_path: str = ""
    log_dir: str = ""

    # Runtime
    open_browser: bool = False  # never by default


def _load_config() -> Config:
    """Load config from environment. Called once."""
    root = Path(os.getenv("FLOWBRAIN_ROOT", "")).resolve() if os.getenv("FLOWBRAIN_ROOT") else Path.cwd()

    # Check for FLOWBRAIN_ prefixed vars first, fall back to legacy names
    host = os.getenv("FLOWBRAIN_HOST", os.getenv("HOST", "127.0.0.1"))
    port = int(os.getenv("FLOWBRAIN_PORT", os.getenv("PORT", "8001")))

    flowbrain_url = os.getenv("FLOWBRAIN_URL", os.getenv("FLOW_FINDER_URL", f"http://127.0.0.1:{port}"))
    n8n_base_url = os.getenv("N8N_BASE_URL", "http://localhost:5678")
    n8n_webhook = os.getenv("N8N_DEFAULT_WEBHOOK", "")

    data_dir = root / "data"
    log_dir = data_dir / "logs"
    db_path = data_dir / "flowbrain.db"

    return Config(
        host=host,
        port=port,
        flow_finder_url=flowbrain_url,
        n8n_base_url=n8n_base_url,
        n8n_default_webhook=n8n_webhook,
        min_autoexec_confidence=float(os.getenv("FLOWBRAIN_MIN_AUTOEXEC_CONFIDENCE", "0.85")),
        min_preview_confidence=float(os.getenv("FLOWBRAIN_MIN_PREVIEW_CONFIDENCE", "0.40")),
        min_search_confidence=float(os.getenv("FLOWBRAIN_MIN_SEARCH_CONFIDENCE", "0.30")),
        default_auto_execute=os.getenv("FLOWBRAIN_AUTO_EXECUTE", "false").lower() in ("true", "1", "yes"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        project_root=str(root),
        data_dir=str(data_dir),
        db_path=str(db_path),
        log_dir=str(log_dir),
        open_browser=os.getenv("FLOWBRAIN_OPEN_BROWSER", "false").lower() in ("true", "1", "yes"),
    )


# Singleton — created once on import
_config: Config | None = None


def get_config() -> Config:
    """Get the global config singleton."""
    global _config
    if _config is None:
        _config = _load_config()
    return _config
