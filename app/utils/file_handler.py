import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
_COOKIES_FILE: Path = BASE_DIR / "cookies.txt"

_cookie_file: Path | None = None


# ---------------------------------------------------------------------------
# Public setup functions (called from lifespan in main.py)
# ---------------------------------------------------------------------------

def ensure_downloads_dir() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def setup_cookies() -> None:
    """Load cookies.txt from the project root.

    The file is committed directly to the repository so it is available
    on every deployment automatically.  No env vars, no encoding, no
    external secrets management needed.

    To refresh: run scripts/filter_yt_cookies.py with a fresh browser
    export, replace cookies.txt, commit, and push.
    """
    global _cookie_file

    if _COOKIES_FILE.exists():
        _cookie_file = _COOKIES_FILE
        lines = [
            l for l in _COOKIES_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            if l.strip() and not l.startswith("#")
        ]
        logger.info(
            "YouTube cookies loaded from %s (%d cookie lines)",
            _COOKIES_FILE, len(lines),
        )
    else:
        logger.warning(
            "No cookies.txt found at %s. YouTube may rate-limit requests.",
            _COOKIES_FILE,
        )


# ---------------------------------------------------------------------------
# Accessors used by downloader.py
# ---------------------------------------------------------------------------

def get_cookie_file() -> Path | None:
    return _cookie_file
