import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
import requests

logger = logging.getLogger(__name__)

from app.services.downloader import DownloaderService
from app.utils.file_handler import DOWNLOADS_DIR
from app.utils.validator import validate_youtube_url

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

_service = DownloaderService()
# No manual ThreadPoolExecutor needed — asyncio.to_thread() uses the running
# event loop's default executor (a ThreadPoolExecutor) and is the modern,
# idiomatic approach since Python 3.9.


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/formats")
async def get_formats(url: str):
    """Fetch video title, duration and quality options.

    yt-dlp info-extraction is blocking (sync HTTP + JS evaluation).
    asyncio.to_thread() offloads it to the thread pool without stalling
    the event loop or needing a manually managed ThreadPoolExecutor.
    """
    error = validate_youtube_url(url)
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    try:
        result = await asyncio.to_thread(_service.get_formats, url)
        return JSONResponse(content=result)
    except Exception as exc:
        msg = str(exc).removeprefix("ERROR: ").strip()
        return JSONResponse(status_code=500, content={"error": msg})


async def _run_download(job_id: str, url: str, format_id: str) -> None:
    """Async wrapper so BackgroundTasks awaits the coroutine properly.

    yt-dlp download is inherently blocking (file I/O + network).
    asyncio.to_thread() moves it off the event loop into a worker thread,
    while the coroutine itself is tracked by FastAPI's BackgroundTasks.
    """
    await asyncio.to_thread(_service.download, job_id, url, format_id)


@router.post("/download")
async def download_video(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    format_id: str = Form(default="best"),
):
    """Queue a download job and return the job ID immediately.

    The actual download runs as an async background task via _run_download,
    which offloads the blocking yt-dlp call to the thread pool.
    """
    error = validate_youtube_url(url)
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    job_id = str(uuid.uuid4())
    # FastAPI awaits async background tasks — _run_download is a coroutine,
    # so the scheduler tracks it properly throughout its lifetime.
    background_tasks.add_task(_run_download, job_id, url, format_id)
    return JSONResponse(content={"job_id": job_id, "status": "pending"})


@router.get("/file/{job_id}")
async def serve_file(job_id: str):
    """Stream the completed file to the browser and delete it afterwards."""
    job = _service.get_job(job_id)
    if not job or job.get("status") != "completed":
        return JSONResponse(status_code=404, content={"error": "File not ready"})

    filepath = Path(job.get("filepath") or (DOWNLOADS_DIR / job["filename"]))
    if not filepath.exists():
        return JSONResponse(status_code=404, content={"error": "File not found on disk"})

    async def _delete_after_send() -> None:
        """Async cleanup: delete the temp file after it has been streamed."""
        try:
            await asyncio.to_thread(filepath.unlink, True)  # missing_ok=True
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


@router.get("/direct/{job_id}")
async def serve_direct_file(job_id: str):
    """Stream a browser-direct fallback URL through this app.

    This keeps the response same-origin for the browser, so the frontend can
    show progress and save a Blob. If Render's IP is blocked, configure
    YTDLP_PROXY_URL so this server-side stream uses a clean egress IP.
    """
    job = _service.get_job(job_id)
    if not job or job.get("status") != "completed" or not job.get("direct_url"):
        return JSONResponse(status_code=404, content={"error": "Direct URL not ready"})

    direct_url = job["direct_url"]
    filename = job.get("filename") or "video.mp4"
    proxy_url = os.environ.get("YTDLP_PROXY_URL", "").strip()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    def _open_stream():
        return requests.get(
            direct_url,
            stream=True,
            timeout=60,
            headers={"User-Agent": "Mozilla/5.0"},
            proxies=proxies,
        )

    try:
        upstream = await asyncio.to_thread(_open_stream)
        upstream.raise_for_status()
    except Exception as exc:
        logger.warning("Direct stream failed for job=%s: %s", job_id, exc)
        return JSONResponse(
            status_code=502,
            content={
                "error": (
                    "Server could not stream the fallback URL. Configure "
                    "YTDLP_PROXY_URL on Render for direct saving."
                )
            },
        )

    def _iter_content():
        try:
            for chunk in upstream.iter_content(chunk_size=262_144):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if upstream.headers.get("content-length"):
        headers["Content-Length"] = upstream.headers["content-length"]

    return StreamingResponse(
        _iter_content(),
        media_type=upstream.headers.get("content-type") or "video/mp4",
        headers=headers,
    )


@router.get("/status/{job_id}")
async def job_status(job_id: str):
    """Return live job status including download progress fields."""
    job = _service.get_job(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return JSONResponse(content=job)
