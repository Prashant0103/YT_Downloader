import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.youtube_api import search_videos

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search")
async def search(q: str, max_results: int = 8):
    """Search YouTube via the Data API v3.

    The googleapiclient HTTP calls are blocking (httplib2-based).  Running them
    directly in an async handler would stall the entire event loop for every
    concurrent request.  asyncio.to_thread() offloads the work to the default
    thread-pool executor so the event loop stays free.

    Query params:
      q           – search query (required)
      max_results – number of results (default 8, max 50)
    """
    q = q.strip()
    if not q:
        return JSONResponse(
            status_code=400,
            content={"error": "Query parameter 'q' is required."},
        )

    max_results = max(1, min(max_results, 50))

    try:
        # Offload ALL blocking googleapiclient / httplib2 I/O to a thread.
        results = await asyncio.to_thread(search_videos, q, max_results)
        return JSONResponse(content={"results": results})

    except RuntimeError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    except Exception as exc:
        logger.exception("YouTube API search failed: %s", exc)
        return JSONResponse(
            status_code=502, content={"error": f"YouTube API error: {exc}"}
        )
