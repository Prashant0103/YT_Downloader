import logging
import os
import re
from typing import Optional

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


def _api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set in environment variables.")
    return key


def _youtube_client():
    """Build and return a YouTube Data API v3 client (demo.py approach)."""
    return build("youtube", "v3", developerKey=_api_key())


def search_videos(query: str, max_results: int = 8) -> list[dict]:
    """Search YouTube via the Data API v3 using googleapiclient.discovery.

    Mirrors the approach in demo.py:
      youtube = build("youtube", "v3", developerKey=API_KEY)
      request = youtube.search().list(part="snippet", q=..., type="video", ...)
      response = request.execute()

    Returns a list of dicts:
      {
        "video_id": str,
        "title":    str,
        "channel":  str,
        "thumbnail": str,   # URL of medium-res thumbnail
        "duration":  str,   # human-readable e.g. "3:45"
        "url":       str,   # full watch URL
      }
    """
    youtube = _youtube_client()

    # Step 1: search for video IDs + snippet data (same as demo.py)
    search_request = youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=max_results,
    )
    search_response = search_request.execute()

    items = search_response.get("items", [])
    if not items:
        return []

    video_ids = [item["id"]["videoId"] for item in items]

    # Step 2: fetch contentDetails for durations
    details_request = youtube.videos().list(
        part="contentDetails",
        id=",".join(video_ids),
    )
    details_response = details_request.execute()

    duration_map: dict[str, str] = {}
    for v in details_response.get("items", []):
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


def search_shorts(query: str, max_results: int = 8) -> list[dict]:
    """Search specifically for YouTube Shorts (videoDuration='short').

    This mirrors the demo.py approach for finding short-form videos:
      request = youtube.search().list(
          part="snippet",
          q=query,
          type="video",
          videoDuration="short",
          ...
      )

    Returns same structure as search_videos().
    """
    youtube = _youtube_client()

    search_request = youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=max_results,
        videoDuration="short",   # Shorts filter from demo.py
    )
    search_response = search_request.execute()

    items = search_response.get("items", [])
    if not items:
        return []

    video_ids = [item["id"]["videoId"] for item in items]

    details_request = youtube.videos().list(
        part="contentDetails",
        id=",".join(video_ids),
    )
    details_response = details_request.execute()

    duration_map: dict[str, str] = {}
    for v in details_response.get("items", []):
        vid_id = v["id"]
        duration_map[vid_id] = v.get("contentDetails", {}).get("duration", "")

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
        # Use the /shorts/ URL format (like demo.py)
        results.append({
            "video_id": vid_id,
            "title":    snippet.get("title", ""),
            "channel":  snippet.get("channelTitle", ""),
            "thumbnail": thumb,
            "duration":  _parse_duration(duration_map.get(vid_id, "")),
            "url":       f"https://www.youtube.com/shorts/{vid_id}",
        })

    return results


# ---------------------------------------------------------------------------
# ISO 8601 duration → human-readable "H:MM:SS" / "M:SS"
# ---------------------------------------------------------------------------

def _parse_duration(iso: str) -> str:
    """Convert PT1H3M45S → '1:03:45', PT3M5S → '3:05', PT45S → '0:45'."""
    if not iso or not iso.startswith("PT"):
        return ""
    h = int((re.search(r"(\d+)H", iso) or [None, 0])[1])
    m = int((re.search(r"(\d+)M", iso) or [None, 0])[1])
    s = int((re.search(r"(\d+)S", iso) or [None, 0])[1])
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
