import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes.download import router
from app.utils.file_handler import ensure_downloads_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_downloads_dir()
    yield


app = FastAPI(title="YouTube Video Downloader", lifespan=lifespan)
app.include_router(router)
