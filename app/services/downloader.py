import logging
import threading
from pathlib import Path
from enum import Enum
from typing import Optional

import imageio_ffmpeg
import yt_dlp

from app.utils.file_handler import DOWNLOADS_DIR, get_cookie_file, is_oauth2_active

# Bundled static binary — works on Render and any env without system ffmpeg
_FFMPEG_PATH: str = imageio_ffmpeg.get_ffmpeg_exe()

logger = logging.getLogger(__name__)

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
        ydl_opts = {"quiet": True, "no_warnings": True, "ffmpeg_location": _FFMPEG_PATH}
        _apply_auth(ydl_opts)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return _parse_formats(info)

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
        ydl_opts = {
            "outtmpl": str(DOWNLOADS_DIR / "%(title)s.%(ext)s"),
            "format": fmt,
            "merge_output_format": "mp4",
            "restrictfilenames": True,
            "quiet": True,
            "no_warnings": False,
            "ffmpeg_location": _FFMPEG_PATH,
        }
        _apply_auth(ydl_opts)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
            "format_key": str(res),
            "size_mb": size_mb,
        })

    return {
        "title": info.get("title", "Unknown"),
        "duration": info.get("duration"),
        "formats": result,
    }


def _best_video_for_height(formats: list, max_height: int) -> Optional[dict]:
    # Prefer DASH video-only streams — matches what FORMAT_MAP actually downloads
    candidates = [
        f for f in formats
        if f.get("height") and f["height"] <= max_height
        and f.get("vcodec") and f["vcodec"] != "none"
        and f.get("acodec") == "none"
    ]
    if not candidates:
        # Fall back to progressive (video+audio combined)
        candidates = [
            f for f in formats
            if f.get("height") and f["height"] <= max_height
            and f.get("vcodec") and f["vcodec"] != "none"
        ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: (f.get("height") or 0, f.get("vbr") or f.get("tbr") or 0))


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
    """Apply the best available auth: OAuth2 tokens > cookies file > no auth."""
    if is_oauth2_active():
        opts["username"] = "oauth2"
        opts["password"] = ""
        # The OAuth2 credentials belong to the YouTube TV client.
        # Force tv_embedded so the innertube API request format matches the
        # Bearer token type -- mismatching client causes HTTP 400.
        opts["extractor_args"] = {"youtube": {"player_client": ["tv_embedded", "web"]}}
        return
    cf = get_cookie_file()
    if cf and cf.exists():
        opts["cookiefile"] = str(cf)


def _resolve_filepath(ydl: yt_dlp.YoutubeDL, info: dict) -> str:
    requested = info.get("requested_downloads")
    if requested:
        entry = requested[0]
        return entry.get("filepath") or entry.get("filename") or ""
    return str(Path(ydl.prepare_filename(info)).with_suffix(".mp4"))
