import logging
import os
import shutil
import threading
from pathlib import Path
from enum import Enum
from typing import Optional

import imageio_ffmpeg
import yt_dlp

from app.utils.file_handler import DOWNLOADS_DIR, get_cookie_file

# Bundled static binary — works on Render and any env without system ffmpeg
_FFMPEG_PATH: str = imageio_ffmpeg.get_ffmpeg_exe()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Proxy configuration
# ---------------------------------------------------------------------------
# Set the PROXY_URL environment variable to route all yt-dlp traffic through
# a proxy.  Supports HTTP, HTTPS, SOCKS4, and SOCKS5 proxies.
#
# Format examples:
#   http://user:pass@proxy.webshare.io:8080        (HTTP proxy with auth)
#   socks5://user:pass@proxy.webshare.io:1080      (SOCKS5 proxy)
#   http://1.2.3.4:8080                            (HTTP proxy, no auth)
#
# Leave unset (or empty) to use a direct connection (no proxy).
_PROXY_URL: str = os.environ.get("PROXY_URL", "").strip()


def _build_js_runtimes() -> dict:
    """Build a js_runtimes dict with every available JS runtime.

    yt-dlp needs a JS runtime + yt-dlp-ejs scripts to solve YouTube's
    signature and n-parameter challenges.
    """
    runtimes: dict = {}
    if shutil.which("deno"):
        runtimes["deno"] = {}
    node_path = shutil.which("node")
    if node_path:
        runtimes["node"] = {"path": node_path}
    if not runtimes:
        runtimes["deno"] = {}
        logger.warning(
            "No JS runtime (node/deno) found on PATH. "
            "YouTube downloads will likely fail. Install Node.js or Deno."
        )
    else:
        logger.info("JS runtimes available for yt-dlp: %s", list(runtimes.keys()))
    return runtimes


_JS_RUNTIMES: dict = _build_js_runtimes()

def _check_proxy(url: str) -> bool:
    """Return True if the proxy is reachable, False otherwise."""
    import urllib.request
    try:
        proxy_handler = urllib.request.ProxyHandler({"http": url, "https": url})
        opener = urllib.request.build_opener(proxy_handler)
        opener.addheaders = [("User-Agent", "curl/7.88")]
        # Just connect to YouTube's homepage through the proxy with a short timeout
        opener.open("http://www.youtube.com", timeout=8)
        return True
    except Exception as exc:
        logger.error("Proxy health-check FAILED (%s): %s", url, exc)
        return False


if _PROXY_URL:
    logger.info("Proxy configured: %s — running health check...", _PROXY_URL)
    if _check_proxy(_PROXY_URL):
        logger.info("Proxy OK — all yt-dlp traffic will route through proxy")
    else:
        logger.warning(
            "Proxy UNREACHABLE — falling back to direct connection. "
            "Fix PROXY_URL and redeploy to enable the proxy."
        )
        _PROXY_URL = ""   # disable so _base_opts() doesn't inject a broken proxy
else:
    logger.info("No PROXY_URL set — using direct connection")


_RESOLUTIONS = [2160, 1440, 1080, 720, 480, 360]

FORMAT_MAP: dict[str, str] = {
    "2160": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best[height<=2160][acodec!=none]",
    "1440": "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1440]+bestaudio/best[height<=1440][acodec!=none]",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080][acodec!=none]",
    "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720][acodec!=none]",
    "480":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480][acodec!=none]",
    "360":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best[height<=360][acodec!=none]",
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[acodec!=none]",
}


class JobStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Shared ydl_opts builder
# ---------------------------------------------------------------------------

def _base_opts() -> dict:
    """Options common to both format-listing and downloading.

    Client strategy (all three bypass YouTube PO-token requirements):
      android_vr  - primary; no PO token, no JS challenge, datacenter-friendly
      tv_embedded - YouTube TV embedded player; works for bot-challenged videos
      ios         - YouTube iOS app; broad fallback

    NOTE: player_skip intentionally NOT set.  Skipping the webpage removes the
    visitor-session context that some videos need, causing YouTube to trigger
    'confirm you are not a bot' even with valid cookies.  With real cookies
    the webpage loads as an authenticated session (no 429 either).
    """
    opts = {
        "quiet": True,
        "no_warnings": False,
        "ffmpeg_location": _FFMPEG_PATH,
        "js_runtimes": _JS_RUNTIMES,
        "extractor_args": {
            "youtube": {
                "player_client": ["android_vr", "tv_embedded", "ios"],
            }
        },
        # Polite request pacing to reduce 429 likelihood
        "sleep_interval_requests": 1,
        "max_sleep_interval": 5,
        # Retry on transient network / 429 errors
        "retries": 6,
        "fragment_retries": 6,
        "retry_sleep_functions": {"http": lambda n: 2 ** n},  # 2 4 8 16 32 64 s
    }
    # Route through proxy if configured (bypasses datacenter IP flagging)
    if _PROXY_URL:
        opts["proxy"] = _PROXY_URL
    _apply_auth(opts)
    return opts


class DownloaderService:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _set(self, job_id: str, **kwargs) -> None:
        with self._lock:
            self._jobs[job_id].update(kwargs)

    def get_formats(self, url: str) -> dict:
        """Fetch available formats (single attempt, no retries)."""
        _warnings: list[str] = []

        class _Logger:
            def debug(self, msg): pass
            def info(self, msg): pass
            def warning(self, msg): _warnings.append(msg)
            def error(self, msg): _warnings.append(f"ERROR: {msg}")

        opts = _base_opts()
        opts.update({
            "logger": _Logger(),
            "format": "bestvideo*+bestaudio*/bestvideo+bestaudio/best",
            "ignore_no_formats_error": True,
        })

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        result = _parse_formats(info)

        if result["formats"]:
            return result

        # Surface yt-dlp warnings as a useful error
        if _warnings:
            logger.warning("No formats for %s — warnings: %s", url, _warnings)

        hint = ""
        if any("429" in w for w in _warnings):
            hint = " YouTube is rate-limiting this server (HTTP 429). Try again later."
        elif any("Sign in" in w for w in _warnings):
            hint = " YouTube requires fresh cookies for this video."
        raise yt_dlp.utils.DownloadError(
            f"No downloadable formats found for this video.{hint}"
        )

    def download(self, job_id: str, url: str, format_id: str = "best") -> None:
        with self._lock:
            self._jobs[job_id] = {
                "status": JobStatus.PENDING,
                "url": url,
                "filename": None,
                "filepath": None,
                "error": None,
            }

        self._set(job_id, status=JobStatus.DOWNLOADING)
        logger.info("Download started  job=%s format=%s url=%s", job_id, format_id, url)

        fmt = FORMAT_MAP.get(format_id, FORMAT_MAP["best"])
        opts = _base_opts()
        opts.update({
            "outtmpl": str(DOWNLOADS_DIR / "%(title)s.%(ext)s"),
            "format": fmt,
            "merge_output_format": "mp4",
            "restrictfilenames": True,
        })

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = _resolve_filepath(ydl, info)

            filename = Path(filepath).name
            self._set(job_id, status=JobStatus.COMPLETED, filename=filename, filepath=filepath)
            logger.info("Download complete job=%s file=%s", job_id, filename)

        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).removeprefix("ERROR: ").strip()
            self._set(job_id, status=JobStatus.FAILED, error=msg)
            logger.error("Download failed   job=%s error=%s", job_id, msg)

        except Exception as exc:
            self._set(job_id, status=JobStatus.FAILED, error=str(exc))
            logger.exception("Unexpected error  job=%s", job_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_formats(info: dict) -> dict:
    formats = info.get("formats", [])
    audio_size = _best_audio_size(formats)

    seen_heights: set[int] = set()
    result = []

    for res in _RESOLUTIONS:
        vfmt = _best_video_for_height(formats, res)
        if vfmt is None:
            continue
        h = vfmt.get("height") or res
        if h in seen_heights:
            continue
        seen_heights.add(h)

        v_size = vfmt.get("filesize") or vfmt.get("filesize_approx") or 0
        total = v_size + audio_size
        size_mb = round(total / (1024 * 1024), 1) if total > 0 else None

        result.append({
            "label": f"{h}p",
            "format_key": str(h),
            "size_mb": size_mb,
        })

    return {
        "title": info.get("title", "Unknown"),
        "duration": info.get("duration"),
        "formats": result,
    }


def _best_video_for_height(formats: list, max_height: int) -> Optional[dict]:
    """Find the best video format at or below *max_height*."""
    video_fmts = [
        f for f in formats
        if f.get("height") and f.get("vcodec") and f["vcodec"] != "none"
    ]
    # Prefer DASH video-only
    dash = [f for f in video_fmts if f.get("acodec") == "none" and f["height"] <= max_height]
    if dash:
        return max(dash, key=lambda f: (f["height"], f.get("vbr") or f.get("tbr") or 0))

    # Fallback: any stream with video (progressive, HLS, etc.)
    any_vid = [f for f in video_fmts if f["height"] <= max_height]
    if any_vid:
        return max(any_vid, key=lambda f: (f["height"], f.get("vbr") or f.get("tbr") or 0))

    return None


def _best_audio_size(formats: list) -> int:
    audio = [
        f for f in formats
        if f.get("acodec") and f["acodec"] != "none"
        and f.get("vcodec") == "none"
    ]
    if not audio:
        return 0
    best = max(audio, key=lambda f: f.get("abr") or f.get("tbr") or 0)
    return best.get("filesize") or best.get("filesize_approx") or 0


def _apply_auth(opts: dict) -> None:
    """Attach cookies if available."""
    cf = get_cookie_file()
    if cf and cf.exists():
        opts["cookiefile"] = str(cf)


def _resolve_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    requested = info.get("requested_downloads")
    if requested:
        entry = requested[0]
        return entry.get("filepath") or entry.get("filename") or ""
    return str(Path(ydl.prepare_filename(info)).with_suffix(".mp4"))
