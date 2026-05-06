# YT_Downloader — Project Skills

This file is loaded automatically at the start of every conversation to give you full context about this project without needing to re-explore the codebase.

---

## Project Overview

A production-ready **YouTube video downloader** built with **FastAPI + yt-dlp**, deployed on **Render** via Nixpacks. Users paste a YouTube URL, choose a quality, and the server downloads + merges the video in the background before streaming it to the browser. Files are deleted from the server immediately after delivery.

**Live deployment**: Render (nixpacks build)
**Local dev**: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

---

## Tech Stack

| Layer      | Technology                                  |
|------------|---------------------------------------------|
| Backend    | FastAPI + Uvicorn                           |
| Downloader | yt-dlp (with JS runtime for sig challenges) |
| Merging    | ffmpeg bundled via `imageio-ffmpeg`         |
| Templates  | Jinja2                                      |
| Frontend   | Vanilla HTML / CSS / JS                     |
| Deployment | Render + Nixpacks (`nixpacks.toml`)         |

---

## Project Layout

```
YT_Downloader/
├── app/
│   ├── main.py                  # FastAPI app entry point; lifespan hooks
│   ├── routes/
│   │   └── download.py          # All API endpoints + /debug routes
│   ├── services/
│   │   └── downloader.py        # yt-dlp wrapper, FORMAT_MAP, job tracking
│   ├── utils/
│   │   ├── validator.py         # YouTube URL validation (regex + urlparse)
│   │   └── file_handler.py      # DOWNLOADS_DIR, cookies.txt loading
│   ├── static/                  # Static files served at /
│   └── templates/
│       └── index.html           # Glassmorphism UI
├── downloads/                   # Temp video storage (auto-deleted post-send)
├── scripts/                     # Utility/maintenance scripts
├── cookies.txt                  # YouTube session cookies — GITIGNORED
├── nixpacks.toml                # Adds nodejs to Render build environment
├── requirements.txt
└── .Codex/
    ├── AGENTS.md                # This file
    └── settings.local.json      # Bash/Read permission allowlist
```

---

## Key Design Decisions

### ffmpeg
- **Bundled** via `imageio-ffmpeg` (`imageio_ffmpeg.get_ffmpeg_exe()`).
- No system ffmpeg needed locally or on Render.
- Path is stored in `_FFMPEG_PATH` in `downloader.py` and passed as `ffmpeg_location` to every `YoutubeDL` instance.

### JS Runtime (Node.js / Deno)
- yt-dlp needs a JS runtime to solve YouTube's **signature and n-parameter challenges**.
- `_build_js_runtimes()` in `downloader.py` auto-detects `node` and/or `deno` on `PATH`.
- On Render, `nixpacks.toml` adds Node.js: `nixPkgs = ["...", "nodejs"]`.
- If no runtime is found, a warning is logged but the app still starts (downloads will likely fail).

### Cookie Authentication
- Cookies are loaded from `cookies.txt` at the project root on startup via `setup_cookies()` in `file_handler.py`.
- Path: `BASE_DIR / "cookies.txt"` (i.e., next to `requirements.txt`).
- Passed to yt-dlp as `cookiefile` option via `_apply_auth()` in `downloader.py`.
- **`cookies.txt` is gitignored** — must be manually placed or injected via Render Secret Files.
- Without cookies, YouTube may return HTTP 429 (rate limit) or require sign-in.

### Background Download Jobs
- `POST /download` creates a UUID job, stores it in `DownloaderService._jobs` (dict, thread-safe with `threading.Lock`), and delegates to a `BackgroundTasks` task.
- Format-fetching (`GET /formats`) runs in a `ThreadPoolExecutor` so it doesn't block the event loop.
- Job lifecycle: `pending` → `downloading` → `completed` | `failed`.

### Format Selection
- `FORMAT_MAP` in `downloader.py` maps quality keys (`"360"`, `"480"`, `"720"`, `"1080"`, `"1440"`, `"2160"`, `"best"`) to yt-dlp format strings that prefer DASH video + M4A audio, merged into MP4.
- `_parse_formats()` returns a list of `{label, format_key, size_mb}` dicts for the UI.
- File size is an estimate: video filesize + best audio filesize.

### URL Validation
- `validator.py` uses `urlparse` + a regex `^[a-zA-Z0-9_-]{11}$` to extract and validate the video ID.
- Supports: `/watch?v=`, `/shorts/`, `/live/`, `/embed/`, `youtu.be/` paths.
- Rejects playlists and non-YouTube hosts.

---

## API Endpoints

| Method | Endpoint           | Description                                                      |
|--------|--------------------|------------------------------------------------------------------|
| `GET`  | `/`                | Serves the UI (Jinja2 template)                                  |
| `GET`  | `/formats?url=...` | Returns available qualities + estimated sizes                    |
| `POST` | `/download`        | Starts background job, returns `{job_id, status}`               |
| `GET`  | `/status/{job_id}` | Returns `{status, filename, filepath, error}`                   |
| `GET`  | `/file/{job_id}`   | Streams MP4 to browser, deletes file from disk after send       |
| `GET`  | `/debug`           | Diagnostic: JS runtimes, yt-dlp version, cookie info            |
| `GET`  | `/debug/test`      | Live format-fetch against `dQw4w9WgXcQ` to verify the full stack |

---

## Dependencies (`requirements.txt`)

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
yt-dlp[default]>=2025.1.15
jinja2>=3.1.4
python-multipart>=0.0.9
imageio-ffmpeg>=0.5.1
```

> `imageio-ffmpeg` provides the bundled ffmpeg binary.
> `yt-dlp[default]` includes optional dependencies for broader format support.

---

## Common Tasks

### Run locally
```bash
# Activate venv first
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS/Linux

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Update yt-dlp (do this when YouTube breaks downloads)
```bash
pip install -U yt-dlp
```

### Refresh cookies
1. Log into YouTube in a browser
2. Export cookies using *Get cookies.txt LOCALLY* (Chrome extension) in Netscape format
3. Replace `cookies.txt` at the project root
4. Restart the server (or re-deploy to Render)

### Check deployment health
- `GET /debug` — shows Node.js path, yt-dlp version, cookie file status
- `GET /debug/test` — fetches formats for a test video end-to-end

---

## Known Issues / Gotchas

- **HTTP 429 (Render / datacenter IPs)**: YouTube aggressively rate-limits datacenter IPs. **Fix applied**: `_base_opts()` forces `extractor_args: {youtube: {player_client: ["android_vr", "mweb"]}}`. These clients bypass YouTube's Proof-of-Origin (PO) token and JS-challenge requirements, making them far more reliable from cloud hosts. Additionally, `retries: 6` with exponential backoff (`2^n` seconds) and `sleep_interval_requests: 1` are set. If 429s persist after this, fresh `cookies.txt` is the next mitigation.
- **No JS runtime**: If Node.js is missing on the server, yt-dlp will fail to resolve YouTube's obfuscated URLs for the `web` client. With `android_vr`/`mweb` configured, JS is NOT required — but `nixpacks.toml` still installs Node.js as a safety net.
- **Stale cookies**: `cookies.txt` expires. If downloads suddenly fail with "Sign in" errors, re-export and replace cookies.
- **File size estimates**: YouTube doesn't always expose exact stream sizes; `size_mb` in the format list may be `null`.
- **Restricted filenames**: yt-dlp is configured with `restrictfilenames: True` — special characters in video titles are sanitized.
- **Playlist URLs**: Not supported. Validation rejects URLs without a single video ID.

