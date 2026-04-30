import re
from urllib.parse import urlparse, parse_qs

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def validate_youtube_url(url: str) -> str | None:
    """Return an error string if invalid, None if valid."""
    url = (url or "").strip()
    if not url:
        return "URL is required."

    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format."

    if parsed.scheme not in ("http", "https"):
        return "URL must start with http:// or https://."

    if parsed.netloc.lower() not in _YOUTUBE_HOSTS:
        return "Only YouTube URLs are supported."

    if not _extract_video_id(parsed):
        return "Could not find a valid video ID in the URL."

    return None


def _extract_video_id(parsed) -> str | None:
    host = parsed.netloc.lower()

    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0].split("?")[0]
        return vid if _VIDEO_ID_RE.match(vid) else None

    path = parsed.path
    qs = parse_qs(parsed.query)

    if "/watch" in path:
        vid = qs.get("v", [None])[0]
        return vid if vid and _VIDEO_ID_RE.match(vid) else None

    for prefix in ("/shorts/", "/embed/", "/live/"):
        if prefix in path:
            vid = path.split(prefix, 1)[1].split("/")[0].split("?")[0]
            return vid if _VIDEO_ID_RE.match(vid) else None

    return None
