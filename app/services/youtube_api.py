import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def _api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set in environment variables.")
    return key


def search_videos(query: str, max_results: int = 8) -> list[dict]:
    """Search YouTube via the Data API v3.

    Returns a list of dicts:
      {
        "video_id": str,
        "title":    str,
        "channel":  str,
        "thumbnail": str,   # URL of medium-res thumbnail
        "duration":  str,   # ISO 8601 duration, e.g. "PT3M45S" (may be "" if unavailable)
        "url":       str,   # full watch URL
      }
    """
    key = _api_key()

    # Step 1: search for video IDs + snippet data
    search_params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": key,
    }
    resp = requests.get(_SEARCH_URL, params=search_params, timeout=10)
    resp.raise_for_status()
    search_data = resp.json()

    items = search_data.get("items", [])
    if not items:
        return []

    video_ids = [item["id"]["videoId"] for item in items]

    # Step 2: fetch contentDetails for ISO durations
    details_params = {
        "part": "contentDetails",
        "id": ",".join(video_ids),
        "key": key,
    }
    details_resp = requests.get(_VIDEOS_URL, params=details_params, timeout=10)
    details_resp.raise_for_status()
    details_data = details_resp.json()

    duration_map: dict[str, str] = {}
    for v in details_data.get("items", []):
        vid_id = v["id"]
        duration_map[vid_id] = v.get("contentDetails", {}).get("duration", "")

    # Step 3: build clean result list
    results = []
    for item in items:
        vid_id: str = item["id"]["videoId"]
        snippet: dict = item.get("snippet", {})
        thumbnails: dict = snippet.get("thumbnails", {})
        thumb: str = (
            thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )
        results.append({
            "video_id": vid_id,
            "title":    snippet.get("title", ""),
            "channel":  snippet.get("channelTitle", ""),
            "thumbnail": thumb,
            "duration":  _parse_duration(duration_map.get(vid_id, "")),
            "url":       f"https://www.youtube.com/watch?v={vid_id}",
        })

    return results


# ---------------------------------------------------------------------------
# ISO 8601 duration → human-readable "H:MM:SS" / "M:SS"
# ---------------------------------------------------------------------------

def _parse_duration(iso: str) -> str:
    """Convert PT1H3M45S → '1:03:45', PT3M5S → '3:05', PT45S → '0:45'."""
    if not iso or not iso.startswith("PT"):
        return ""
    import re
    h = int((re.search(r"(\d+)H", iso) or [None, 0])[1])
    m = int((re.search(r"(\d+)M", iso) or [None, 0])[1])
    s = int((re.search(r"(\d+)S", iso) or [None, 0])[1])
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
