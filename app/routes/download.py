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
    """Diagnostic endpoint — shows JS runtime availability and yt-dlp config."""
    import yt_dlp

    node_path = shutil.which("node")
    deno_path = shutil.which("deno")

    # Check if yt-dlp-ejs is installed
    ejs_installed = False
    try:
        import yt_dlp_ejs  # noqa: F401
        ejs_installed = True
    except ImportError:
        pass

    return JSONResponse(content={
        "node_found": node_path or False,
        "deno_found": deno_path or False,
        "js_runtimes_config": {k: str(v) for k, v in _JS_RUNTIMES.items()},
        "yt_dlp_version": yt_dlp.version.__version__,
        "yt_dlp_ejs_installed": ejs_installed,
        "path_env": os.environ.get("PATH", "")[:500],
    })


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
