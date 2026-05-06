"""
Invidious fallback downloader.

YouTube's CDN blocks datacenter IPs (Render, AWS, etc.) with HTTP 403.
Invidious is an open-source YouTube frontend that proxies video streams
through its own servers, bypassing the IP restriction entirely.

Flow:
  1. yt-dlp direct download → 403 on Render
  2. Invidious API → get proxy stream URL (through Invidious server)
  3. Download that URL → goes  User ← our_server ← Invidious ← YouTube CDN
     Invidious servers are not datacenter-blocked by YouTube.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Public Invidious instances — tried in order until one responds.
# List sourced from https://api.invidious.io (filter: api=true, cors=true)
_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.privacyredirect.com",
    "https://iv.datura.network",
    "https://invidious.nerdvpn.de",
    "https://invidious.materialio.us",
    "https://yt.artemislena.eu",
]

_VIDEO_ID_RE = re.compile(
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})"
)


def extract_video_id(url: str) -> Optional[str]:
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def _sanitize(name: str) -> str:
    """Strip characters not safe for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def get_stream_info(video_url: str, max_height: int = 720) -> Optional[dict]:
    """Try each Invidious instance and return the best progressive stream info.

    Returns dict with keys: url, title, height, instance
    Returns None if all instances fail.
    """
    video_id = extract_video_id(video_url)
    if not video_id:
        logger.error("Could not extract video ID from %s", video_url)
        return None

    for instance in _INSTANCES:
        try:
            resp = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                params={"fields": "title,lengthSeconds,formatStreams"},
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                logger.debug("Invidious %s → HTTP %d", instance, resp.status_code)
                continue

            data = resp.json()
            title = data.get("title", video_id)

            # formatStreams = combined video+audio progressive streams (≤720p)
            best: Optional[dict] = None
            best_h = 0
            for fmt in data.get("formatStreams", []):
                res = fmt.get("resolution", "0p")
                try:
                    h = int(res.replace("p", ""))
                except ValueError:
                    continue
                if h <= max_height and h > best_h:
                    best_h = h
                    best = fmt

            if best:
                logger.info(
                    "Invidious %s found stream %dp for %s",
                    instance, best_h, video_id,
                )
                return {
                    "url":      best["url"],
                    "title":    title,
                    "height":   best_h,
                    "instance": instance,
                }

            logger.debug("Invidious %s: no stream ≤%dp", instance, max_height)

        except Exception as exc:
            logger.warning("Invidious %s error: %s", instance, exc)

    logger.error("All Invidious instances failed for %s", video_id)
    return None


def download_stream(
    video_url: str,
    max_height: int,
    dest_dir: Path,
    progress_cb=None,
) -> str:
    """Download via Invidious proxy. Returns the saved filepath string.

    progress_cb(downloaded_bytes, total_bytes, speed_bps, eta_seconds)
    """
    info = get_stream_info(video_url, max_height)
    if not info:
        raise RuntimeError(
            "YouTube is blocking downloads from this server IP. "
            "All Invidious fallback instances also failed. "
            "Try again later or use a different video."
        )

    stream_url = info["url"]
    safe_title  = _sanitize(info["title"])
    height      = info["height"]
    filepath    = dest_dir / f"{safe_title}_{height}p.mp4"

    logger.info(
        "Downloading via Invidious (%s) → %s", info["instance"], filepath.name
    )

    with requests.get(stream_url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total      = int(resp.headers.get("content-length", 0))
        downloaded = 0
        start_ts   = time.monotonic()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=131_072):  # 128 KB
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                if progress_cb:
                    elapsed = time.monotonic() - start_ts or 0.001
                    speed   = int(downloaded / elapsed)
                    eta     = int((total - downloaded) / speed) if speed and total else 0
                    pct     = round(downloaded / total * 100, 1) if total else 0
                    progress_cb(pct, downloaded, total, speed, eta)

    logger.info("Invidious download complete: %s (%d bytes)", filepath.name, downloaded)
    return str(filepath)
