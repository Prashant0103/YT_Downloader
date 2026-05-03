import asyncio
import logging
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)

from app.services.downloader import DownloaderService, _JS_RUNTIMES
from app.utils.file_handler import DOWNLOADS_DIR
from app.utils.validator import validate_youtube_url

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

_service = DownloaderService()
# Run blocking yt-dlp format-fetching in a thread so the event loop isn't stalled
_executor = ThreadPoolExecutor(max_workers=4)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/debug")
async def debug_info():
    """Diagnostic endpoint — shows JS runtime, cookie, and yt-dlp status."""
    import yt_dlp
    from app.utils.file_handler import get_cookie_file

    node_path = shutil.which("node")
    deno_path = shutil.which("deno")

    # Check if yt-dlp-ejs is installed
    ejs_installed = False
    try:
        import yt_dlp_ejs  # noqa: F401
        ejs_installed = True
    except ImportError:
        pass

    # Check cookie status
    cookie_file = get_cookie_file()
    cookie_info = {"loaded": False}
    if cookie_file:
        cookie_info["loaded"] = True
        cookie_info["path"] = str(cookie_file)
        cookie_info["exists"] = cookie_file.exists()
        if cookie_file.exists():
            content = cookie_file.read_text(encoding="utf-8", errors="replace")
            cookie_info["lines"] = len(content.splitlines())
            cookie_info["size_bytes"] = len(content)
            cookie_info["first_80_chars"] = content[:80]

    # Check env var
    yt_cookies_env = os.environ.get("YOUTUBE_COOKIES", "")
    cookie_info["env_var_set"] = bool(yt_cookies_env.strip())
    cookie_info["env_var_length"] = len(yt_cookies_env)
    cookie_info["env_var_preview"] = yt_cookies_env[:120] if yt_cookies_env else ""

    return JSONResponse(content={
        "node_found": node_path or False,
        "deno_found": deno_path or False,
        "js_runtimes_config": {k: str(v) for k, v in _JS_RUNTIMES.items()},
        "yt_dlp_version": yt_dlp.version.__version__,
        "yt_dlp_ejs_installed": ejs_installed,
        "player_client": "android_vr, tv_embedded, ios",
        "cookie_info": cookie_info,
        "path_env": os.environ.get("PATH", "")[:500],
    })


@router.get("/debug/test")
async def debug_test(url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"):
    """Test fetching formats for any video and return raw yt-dlp results.

    Pass ?url=<youtube_url> to test a specific video.
    Defaults to Rick Astley (dQw4w9WgXcQ) as a known-good baseline.
    """
    import yt_dlp
    warnings = []

    class WarningLogger:
        def debug(self, msg): pass
        def info(self, msg): pass
        def warning(self, msg): warnings.append(msg)
        def error(self, msg): warnings.append(f"ERROR: {msg}")

    from app.services.downloader import _base_opts
    ydl_opts = _base_opts()
    ydl_opts.update({
        "logger": WarningLogger(),
        "format": "bestvideo*+bestaudio*/bestvideo+bestaudio/best",
        "ignore_no_formats_error": True,
    })

    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])
            video_fmts = [
                f for f in formats
                if f.get("height") and f.get("vcodec") and f["vcodec"] != "none"
            ]
            return {
                "success": True,
                "url_tested": url,
                "title": info.get("title", "?"),
                "age_limit": info.get("age_limit"),
                "availability": info.get("availability"),
                "is_live": info.get("is_live"),
                "channel": info.get("channel"),
                "total_formats": len(formats),
                "video_formats": len(video_fmts),
                "video_heights": sorted(set(f["height"] for f in video_fmts), reverse=True),
                "sample_formats": [
                    {"id": f.get("format_id"), "height": f.get("height"),
                     "vcodec": f.get("vcodec"), "acodec": f.get("acodec")}
                    for f in video_fmts[:12]
                ],
                "warnings": warnings,
                "cookie_used": bool(ydl_opts.get("cookiefile")),
            }
        except Exception as exc:
            return {
                "success": False,
                "url_tested": url,
                "error": str(exc),
                "warnings": warnings,
                "cookie_used": bool(ydl_opts.get("cookiefile")),
            }

    result = await loop.run_in_executor(_executor, _fetch)
    return JSONResponse(content=result)


@router.get("/formats")
async def get_formats(url: str):
    error = validate_youtube_url(url)
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, _service.get_formats, url)
        return JSONResponse(content=result)
    except Exception as exc:
        logger_msg = str(exc).removeprefix("ERROR: ").strip()
        return JSONResponse(status_code=500, content={"error": logger_msg})


@router.post("/download")
async def download_video(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    format_id: str = Form(default="best"),
):
    error = validate_youtube_url(url)
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    job_id = str(uuid.uuid4())
    background_tasks.add_task(_service.download, job_id, url, format_id)
    return JSONResponse(content={"job_id": job_id, "status": "pending"})


@router.get("/file/{job_id}")
async def serve_file(job_id: str):
    job = _service.get_job(job_id)
    if not job or job.get("status") != "completed":
        return JSONResponse(status_code=404, content={"error": "File not ready"})

    filepath = Path(job.get("filepath") or (DOWNLOADS_DIR / job["filename"]))
    if not filepath.exists():
        return JSONResponse(status_code=404, content={"error": "File not found on disk"})

    def _delete_after_send():
        try:
            filepath.unlink(missing_ok=True)
            logger.info("Deleted after browser download: %s", filepath.name)
        except Exception as exc:
            logger.warning("Could not delete %s: %s", filepath.name, exc)

    return FileResponse(
        path=filepath,
        filename=filepath.name,
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filepath.name}"'},
        background=BackgroundTask(_delete_after_send),
    )


@router.get("/status/{job_id}")
async def job_status(job_id: str):
    job = _service.get_job(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return JSONResponse(content=job)
