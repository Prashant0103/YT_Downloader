import base64
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
_COOKIES_FILE: Path = BASE_DIR / "cookies.txt"

_cookie_file: Path | None = None
_oauth2_active: bool = False


# ---------------------------------------------------------------------------
# yt-dlp cache location (where yt-dlp-youtube-oauth2 plugin stores tokens)
# ---------------------------------------------------------------------------

def _ytdlp_cache_dir() -> Path:
    # yt-dlp uses ~/.cache/yt-dlp on all platforms (Windows included)
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "yt-dlp"


_OAUTH2_CACHE_FILE: Path = _ytdlp_cache_dir() / "youtube-oauth2" / "token_data.json"


# ---------------------------------------------------------------------------
# Public setup functions (called from lifespan in main.py)
# ---------------------------------------------------------------------------

def ensure_downloads_dir() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def setup_oauth2() -> None:
    """Restore OAuth2 token from YOUTUBE_OAUTH2_TOKEN env var (Render/CI)."""
    global _oauth2_active

    token_b64 = os.environ.get("YOUTUBE_OAUTH2_TOKEN", "").strip()
    if token_b64:
        try:
            token_json = base64.b64decode(token_b64).decode("utf-8")
            _OAUTH2_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _OAUTH2_CACHE_FILE.write_text(token_json, encoding="utf-8")
            _oauth2_active = True
            logger.info("YouTube OAuth2 token restored from YOUTUBE_OAUTH2_TOKEN env var")
        except Exception as exc:
            logger.warning("Failed to restore OAuth2 token from env var: %s", exc)
        return

    # Local dev: token already in yt-dlp cache from a previous setup_oauth2.py run
    if _OAUTH2_CACHE_FILE.exists():
        _oauth2_active = True
        logger.info("YouTube OAuth2 token found in local yt-dlp cache")


def setup_cookies() -> None:
    """Locate the cookie source at startup (file -> env var -> none)."""
    global _cookie_file

    # Priority 1: cookies.txt written by refresh_cookies.py
    if _COOKIES_FILE.exists():
        _cookie_file = _COOKIES_FILE
        logger.info("YouTube cookies loaded from %s", _COOKIES_FILE)
        return

    # Priority 2: YOUTUBE_COOKIES environment variable (Render / CI)
    content = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if content:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.close()
        _cookie_file = Path(tmp.name)
        logger.info("YouTube cookies loaded from YOUTUBE_COOKIES env var")
        return

    logger.info("No YouTube cookies configured")


# ---------------------------------------------------------------------------
# Accessors used by downloader.py
# ---------------------------------------------------------------------------

def get_cookie_file() -> Path | None:
    return _cookie_file


def is_oauth2_active() -> bool:
    return _oauth2_active
