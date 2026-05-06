"""Invidious fallback downloader.

Render/datacenter IPs can receive HTTP 403 from YouTube's media CDN after
yt-dlp has successfully extracted a video. This module asks public Invidious
instances for locally proxied progressive MP4 streams and downloads through
those instances as a last-resort fallback.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Static fallback instances used if the public registry is unavailable.
_FALLBACK_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.privacyredirect.com",
    "https://iv.datura.network",
    "https://invidious.nerdvpn.de",
    "https://invidious.materialio.us",
    "https://yt.artemislena.eu",
]
_INSTANCES_REGISTRY_URL = "https://api.invidious.io/instances.json"
_INSTANCE_CACHE_TTL_SECONDS = 15 * 60
_instance_cache: tuple[float, list[str]] = (0.0, [])

_VIDEO_ID_RE = re.compile(
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})"
)


def extract_video_id(url: str) -> Optional[str]:
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def _sanitize(name: str) -> str:
    """Strip characters not safe for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def _is_proxied_stream_url(stream_url: str) -> bool:
    host = urlparse(stream_url).netloc.lower()
    return "googlevideo.com" not in host and "youtube.com" not in host


def _get_instances() -> list[str]:
    """Return healthy public Invidious API instances, with static fallback."""
    global _instance_cache

    now = time.monotonic()
    cached_at, cached_instances = _instance_cache
    if cached_instances and now - cached_at < _INSTANCE_CACHE_TTL_SECONDS:
        return cached_instances

    instances: list[str] = []
    try:
        resp = requests.get(
            _INSTANCES_REGISTRY_URL,
            params={"sort_by": "health", "type": "https"},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()

        for row in resp.json():
            if not isinstance(row, list) or len(row) < 2:
                continue
            meta = row[1] or {}
            if not isinstance(meta, dict) or not meta.get("api"):
                continue
            uri = (meta.get("uri") or "").rstrip("/")
            if uri.startswith("https://"):
                instances.append(uri)

    except Exception as exc:
        logger.warning("Could not refresh Invidious instance list: %s", exc)

    merged: list[str] = []
    for instance in instances + _FALLBACK_INSTANCES:
        instance = instance.rstrip("/")
        if instance and instance not in merged:
            merged.append(instance)

    _instance_cache = (now, merged)
    return merged


def get_stream_candidates(video_url: str, max_height: int = 720) -> list[dict]:
    """Try Invidious instances and return progressive stream candidates.

    Returns dicts with keys: url, title, height, instance.
    Returns an empty list if all instances fail.
    """
    video_id = extract_video_id(video_url)
    if not video_id:
        logger.error("Could not extract video ID from %s", video_url)
        return []

    candidates: list[dict] = []
    for instance in _get_instances():
        try:
            resp = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                params={
                    "fields": "title,lengthSeconds,formatStreams",
                    # Without local=true many instances return googlevideo.com
                    # URLs, which can hit the same Render/datacenter 403.
                    "local": "true",
                },
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                logger.debug("Invidious %s -> HTTP %d", instance, resp.status_code)
                continue

            data = resp.json()
            title = data.get("title", video_id)

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

            if best and best.get("url") and _is_proxied_stream_url(best["url"]):
                logger.info(
                    "Invidious %s found stream %dp for %s",
                    instance, best_h, video_id,
                )
                candidates.append({
                    "url": best["url"],
                    "title": title,
                    "height": best_h,
                    "instance": instance,
                })
            elif best and best.get("url"):
                logger.debug("Invidious %s returned direct media URL", instance)
            else:
                logger.debug("Invidious %s: no stream <=%dp", instance, max_height)

        except Exception as exc:
            logger.warning("Invidious %s error: %s", instance, exc)

    if not candidates:
        logger.error("All Invidious instances failed for %s", video_id)
    return sorted(candidates, key=lambda c: c["height"], reverse=True)


def get_stream_info(video_url: str, max_height: int = 720) -> Optional[dict]:
    """Return the best progressive Invidious stream info, if available."""
    candidates = get_stream_candidates(video_url, max_height)
    return candidates[0] if candidates else None


def download_stream(
    video_url: str,
    max_height: int,
    dest_dir: Path,
    progress_cb=None,
) -> str:
    """Download via Invidious proxy. Returns the saved filepath string."""
    candidates = get_stream_candidates(video_url, max_height)
    if not candidates:
        raise RuntimeError(
            "YouTube is blocking downloads from this server IP. "
            "All Invidious fallback instances also failed. "
            "Try again later or use a different video."
        )

    errors: list[str] = []
    for info in candidates:
        stream_url = info["url"]
        safe_title = _sanitize(info["title"])
        height = info["height"]
        filepath = dest_dir / f"{safe_title}_{height}p.mp4"

        logger.info(
            "Downloading via Invidious (%s) -> %s", info["instance"], filepath.name
        )

        try:
            with requests.get(
                stream_url,
                stream=True,
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                start_ts = time.monotonic()

                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=131_072):  # 128 KB
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_cb:
                            elapsed = time.monotonic() - start_ts or 0.001
                            speed = int(downloaded / elapsed)
                            eta = int((total - downloaded) / speed) if speed and total else 0
                            pct = round(downloaded / total * 100, 1) if total else 0
                            progress_cb(pct, downloaded, total, speed, eta)

            logger.info(
                "Invidious download complete: %s (%d bytes)",
                filepath.name,
                downloaded,
            )
            return str(filepath)

        except Exception as exc:
            filepath.unlink(missing_ok=True)
            errors.append(f"{info['instance']}: {exc}")
            logger.warning("Invidious stream failed via %s: %s", info["instance"], exc)

    raise RuntimeError(
        "YouTube is blocking downloads from this server IP. "
        "All Invidious fallback streams failed. "
        f"Last errors: {'; '.join(errors[-3:])}"
    )
