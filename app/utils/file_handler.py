import base64
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
DOWNLOADS_DIR: Path = BASE_DIR / "downloads"

# Ordered list of paths to search for cookies.txt
# Render Secret Files land at /etc/secrets/; local dev uses project root.
_COOKIE_CANDIDATES: list[Path] = [
    BASE_DIR / "cookies.txt",           # local dev / committed file
    Path("/etc/secrets/cookies.txt"),   # Render Secret Files
]

_cookie_file: Path | None = None
_temp_cookie_file: Path | None = None   # tempfile created from env var


# ---------------------------------------------------------------------------
# Public setup functions (called from lifespan in main.py)
# ---------------------------------------------------------------------------

def ensure_downloads_dir() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def setup_cookies() -> None:
    """Locate and activate a cookies.txt file using three strategies, in order:

    1. ``YOUTUBE_COOKIES_B64`` env var — base64-encoded Netscape cookie content.
       Written to a temp file. Highest priority: browser-exported cookies are
       more effective than yt-dlp generated cookies on disk.
    2. ``YOUTUBE_COOKIES`` env var — same but plain text (not base64).
    3. File on disk — checks every path in ``_COOKIE_CANDIDATES``
       (project root for local dev, /etc/secrets/ for Render Secret Files).
       Lowest priority because disk files are often yt-dlp generated and less
       effective than real browser session cookies.

    Sets the module-level ``_cookie_file`` so that ``get_cookie_file()``
    returns the active path for yt-dlp.
    """
    global _cookie_file, _temp_cookie_file

    # ── Strategy 1: base64-encoded env var (browser cookies, best) ──────────
    b64 = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
    if b64:
        try:
            raw = base64.b64decode(b64).decode("utf-8")
            _cookie_file = _write_temp_cookie(raw, source="YOUTUBE_COOKIES_B64 env var")
            return
        except Exception as exc:
            logger.error("Failed to decode YOUTUBE_COOKIES_B64: %s", exc)

    # ── Strategy 2: plain-text env var ──────────────────────────────────────
    raw = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if raw:
        _cookie_file = _write_temp_cookie(raw, source="YOUTUBE_COOKIES env var")
        return

    # ── Strategy 3: file on disk (lowest priority) ──────────────────────────
    for candidate in _COOKIE_CANDIDATES:
        if candidate.exists():
            _cookie_file = candidate
            _log_cookie_loaded(candidate)
            return

    logger.warning(
        "No cookies found (checked env vars YOUTUBE_COOKIES_B64 / YOUTUBE_COOKIES "
        "and disk paths %s). "
        "YouTube will likely rate-limit or block requests.",
        [str(p) for p in _COOKIE_CANDIDATES],
    )


# ---------------------------------------------------------------------------
# Accessors used by downloader.py
# ---------------------------------------------------------------------------

def get_cookie_file() -> Path | None:
    return _cookie_file


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_cookie_loaded(path: Path) -> None:
    lines = [
        l for l in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if l.strip() and not l.startswith("#")
    ]
    logger.info("YouTube cookies loaded from %s (%d cookie lines)", path, len(lines))


def _write_temp_cookie(content: str, source: str) -> Path:
    """Write cookie content to a NamedTemporaryFile and return its path."""
    global _temp_cookie_file
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.flush()
    tmp.close()
    path = Path(tmp.name)
    _temp_cookie_file = path
    lines = [l for l in content.splitlines() if l.strip() and not l.startswith("#")]
    logger.info("YouTube cookies written to temp file from %s (%d cookie lines)", source, len(lines))
    return path
