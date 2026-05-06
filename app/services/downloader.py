import logging
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

_RESOLUTIONS = [2160, 1440, 1080, 720, 480, 360]

# Hardcoded quality labels always shown to the user.
# Decoupled from what YouTube serves during info-extraction so that
# server/datacenter IPs (which get restricted to 360p progressive streams
# during listing) still offer all qualities. The actual download uses
# format selectors + android clients that bypass the restriction.
_QUALITY_OPTIONS = [
    {"label": "4K",    "format_key": "2160"},
    {"label": "1440p", "format_key": "1440"},
    {"label": "1080p", "format_key": "1080"},
    {"label": "720p",  "format_key": "720"},
    {"label": "480p",  "format_key": "480"},
    {"label": "360p",  "format_key": "360"},
]

# Approximate combined video+audio bitrates (Mbps) used to estimate file size.
# size_MB ≈ bitrate_Mbps × duration_seconds / 8
_BITRATES_MBPS: dict[str, float] = {
    "2160": 15.0,   # 4K
    "1440":  8.0,   # 1440p
    "1080":  4.0,   # 1080p
    "720":   2.5,   # 720p
    "480":   1.2,   # 480p
    "360":   0.6,   # 360p
}


# Format selector strategy (each entry has four fallback tiers):
#   Tier 1: DASH video-only (mp4) + DASH audio-only (m4a)  → best quality, needs ffmpeg merge
#   Tier 2: DASH video-only (any) + DASH audio-only (any)  → broader codec support
#   Tier 3: best combined stream with audio (progressive)   → ios/legacy clients
#   Tier 4: best combined stream (no codec filter)          → absolute last resort
#
# Tier 3/4 are critical when ios is the download client: ios only provides
# progressive mp4 streams (video+audio in one file, e.g. format IDs 18/22).
# Without these tiers the selector would fail with "format not available".
FORMAT_MAP: dict[str, str] = {
    "2160": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best[height<=2160][acodec!=none]/best[height<=2160]",
    "1440": "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1440]+bestaudio/best[height<=1440][acodec!=none]/best[height<=1440]",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080][acodec!=none]/best[height<=1080]",
    "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720][acodec!=none]/best[height<=720]",
    "480":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480][acodec!=none]/best[height<=480]",
    "360":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best[height<=360][acodec!=none]/best[height<=360]",
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[acodec!=none]/best",
}


# ---------------------------------------------------------------------------
# Player client lists  (two separate strategies — see WHY below)
# ---------------------------------------------------------------------------

# FORMAT LISTING: android_vr/android first because they return full DASH
# manifests (all resolutions up to 4K) on datacenter IPs without needing
# a PO token.  The 'web' client falls back to 360p progressive-only on
# server IPs without a PO token.
_FORMATS_CLIENT_LIST = ["android_vr", "android", "web", "tv_embedded", "ios"]

# DOWNLOAD: ios MUST be first.
#
# WHY THE 403 HAPPENS:
#   android_vr/android generate CDN video URLs that are cryptographically
#   signed with a nonce derived from the extraction IP.  When the server
#   then fetches bytes from that signed URL, YouTube's CDN validates the
#   nonce against the requesting IP — on datacenter/Render IPs this check
#   fails and the CDN returns HTTP 403: Forbidden.
#
# WHY ios FIXES IT:
#   The iOS client generates CDN URLs using a different signing scheme that
#   is NOT IP-bound.  The URLs work from any server IP, which is why this
#   is the standard fix recommended by yt-dlp maintainers for server-side
#   deployments that hit 403 on the actual byte-fetch step.
_DOWNLOAD_CLIENT_LIST = ["ios", "tv_embedded", "mweb", "android", "web"]


class JobStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Shared ydl_opts builder
# ---------------------------------------------------------------------------

def _base_opts(client_list: list[str] | None = None) -> dict:
    """Build yt-dlp options.

    Pass *client_list* to override the player_client order:
      - _FORMATS_CLIENT_LIST  for format/info extraction (android_vr first)
      - _DOWNLOAD_CLIENT_LIST for actual download       (ios first)

    The two lists exist because the optimal client differs per phase:
      android_vr gets the richest DASH format list but generates IP-bound
      CDN URLs that 403 on server IPs at download time.  ios generates
      universally-fetchable CDN URLs at the cost of a slightly smaller
      initial format list (compensated by the other fallbacks).
    """
    opts = {
        "quiet": True,
        "no_warnings": False,
        "ffmpeg_location": _FFMPEG_PATH,
        "js_runtimes": _JS_RUNTIMES,
        "extractor_args": {
            "youtube": {
                "player_client": client_list or _FORMATS_CLIENT_LIST,
            }
        },
        # Mimic a real browser so YouTube doesn't flag the request
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
        # Polite request pacing to reduce 429 likelihood
        "sleep_interval_requests": 1,
        "max_sleep_interval": 5,
        # Retry on transient network / 429 errors
        "retries": 6,
        "fragment_retries": 6,
        "retry_sleep_functions": {"http": lambda n: 2 ** n},  # 2 4 8 16 32 64 s
    }
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
        """Fetch video metadata and return all quality options.

        Uses _FORMATS_CLIENT_LIST (android_vr first) to get the richest DASH
        manifest.  The player client used here does NOT affect download URLs.
        """
        _warnings: list[str] = []

        class _Logger:
            def debug(self, msg): pass
            def info(self, msg): pass
            def warning(self, msg): _warnings.append(msg)
            def error(self, msg): _warnings.append(f"ERROR: {msg}")

        opts = _base_opts(client_list=_FORMATS_CLIENT_LIST)  # android_vr first
        opts.update({
            "logger": _Logger(),
            "format": "bestvideo*+bestaudio*/bestvideo+bestaudio/best",
            "ignore_no_formats_error": True,
            "skip_download": True,
        })

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            if _warnings:
                logger.warning("No info for %s — warnings: %s", url, _warnings)
            hint = ""
            if any("429" in w for w in _warnings):
                hint = " YouTube is rate-limiting this server (HTTP 429). Try again later."
            elif any("Sign in" in w for w in _warnings):
                hint = " YouTube requires fresh cookies for this video."
            raise yt_dlp.utils.DownloadError(
                f"Could not fetch video information.{hint}"
            )

        # Log the raw heights returned so you can inspect prod server logs.
        raw_fmts = info.get("formats", [])
        raw_heights = sorted(set(
            f.get("height") for f in raw_fmts if f.get("height")
        ))
        logger.info(
            "get_formats url=%s title=%r raw_heights=%s warnings=%s",
            url, info.get("title", ""), raw_heights, _warnings or None,
        )

        # Always return the full hardcoded quality menu with estimated sizes.
        # Size is estimated as: bitrate_Mbps × duration_seconds / 8.
        duration = info.get("duration") or 0
        return {
            "title":    info.get("title", "Unknown"),
            "duration": duration,
            "formats":  [
                {
                    "label":      q["label"],
                    "format_key": q["format_key"],
                    "size_mb":    (
                        round(_BITRATES_MBPS[q["format_key"]] * duration / 8, 1)
                        if duration else None
                    ),
                }
                for q in _QUALITY_OPTIONS
            ],
        }

    def _make_progress_hook(self, job_id: str):
        """Return a yt-dlp progress hook that writes live stats to the job dict.

        DASH downloads have two streams: video then audio.  We map them to
        0-50% (video) and 50-100% (audio) so the bar moves smoothly end-to-end.
        A single-stream (progressive) download uses the full 0-100% range.
        """
        state = {"phase": 0}  # incremented each time a stream finishes

        def hook(d: dict) -> None:
            status = d.get("status")
            if status == "downloading":
                dl    = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                speed = int(d.get("speed") or 0)
                eta   = int(d.get("eta")   or 0)
                pct   = dl / total * 100 if total else 0

                if state["phase"] == 0:
                    # First stream: fill the first 50% (will snap to 50 on finish)
                    display = pct * 0.5
                else:
                    # Second stream (audio): fill 50-100%
                    display = 50 + pct * 0.5

                self._set(job_id,
                    progress=round(display, 1),
                    downloaded_bytes=dl,
                    total_bytes=total,
                    speed_bytes=speed,
                    eta_seconds=eta,
                )

            elif status == "finished":
                state["phase"] += 1
                if state["phase"] == 1:
                    # First stream done — snap to 50% while audio begins
                    self._set(job_id, progress=50.0, speed_bytes=0, eta_seconds=0)

        return hook

    def download(self, job_id: str, url: str, format_id: str = "best") -> None:
        with self._lock:
            self._jobs[job_id] = {
                "status":           JobStatus.PENDING,
                "url":              url,
                "filename":         None,
                "filepath":         None,
                "error":            None,
                # Progress fields (updated live via progress hook)
                "progress":         0.0,
                "downloaded_bytes": 0,
                "total_bytes":      0,
                "speed_bytes":      0,
                "eta_seconds":      0,
            }

        self._set(job_id, status=JobStatus.DOWNLOADING)
        logger.info("Download started  job=%s format=%s url=%s", job_id, format_id, url)

        fmt = FORMAT_MAP.get(format_id, FORMAT_MAP["best"])
        opts = _base_opts(client_list=_DOWNLOAD_CLIENT_LIST)  # ios first → no 403
        opts.update({
            "outtmpl":              str(DOWNLOADS_DIR / "%(title)s.%(ext)s"),
            "format":               fmt,
            "merge_output_format":  "mp4",
            "restrictfilenames":    True,
            "progress_hooks":       [self._make_progress_hook(job_id)],
            # NOTE: check_formats is intentionally NOT set.
            # Setting it to 'selected' validates the format selector against
            # the ios client's format list BEFORE trying fallback tiers.
            # ios only serves progressive streams (no separate DASH audio),
            # so the bestvideo+bestaudio merge check always fails even though
            # the /best[height<=N] fallback tier would succeed.
            # Fragment parallelism for DASH multi-part streams.
            "concurrent_fragment_downloads": 2,
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
