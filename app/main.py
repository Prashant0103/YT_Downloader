import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes.download import router
from app.utils.file_handler import ensure_downloads_dir, setup_cookies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_downloads_dir()
    setup_cookies()  # Load YOUTUBE_COOKIES env var cookie file if set
    yield


app = FastAPI(title="YouTube Video Downloader", lifespan=lifespan)
app.include_router(router)

# Mounted last so API routes always take priority.
# Serves any file placed in app/static/ at the root path.
app.mount("/", StaticFiles(directory=_STATIC_DIR), name="static")
