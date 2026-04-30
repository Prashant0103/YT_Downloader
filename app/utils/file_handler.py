import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
DOWNLOADS_DIR: Path = BASE_DIR / "downloads"

_cookie_file: Path | None = None


def ensure_downloads_dir() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def setup_cookies() -> None:
    """Write YOUTUBE_COOKIES env var to a temp file for yt-dlp to use."""
    global _cookie_file
    content = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if not content:
        logger.info("No YOUTUBE_COOKIES env var found — running without cookies")
        return
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    tmp.write(content)
    tmp.close()
    _cookie_file = Path(tmp.name)
    logger.info("YouTube cookies loaded from environment variable")


def get_cookie_file() -> Path | None:
    return _cookie_file
