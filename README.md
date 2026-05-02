# YouTube Video Downloader

A production-ready YouTube video downloader built with **FastAPI** and **yt-dlp**. Features a modern glassmorphism UI, quality selection with estimated file sizes, and background download processing.

Deployed on **[Render](https://render.com)** via Nixpacks.

---

## Features

- Download YouTube videos in any available quality (360p → 4K)
- Quality selector with estimated file sizes per resolution
- Automatic browser download after server-side processing
- Background task processing — the event loop never blocks
- Downloaded files are auto-deleted from the server after delivery
- Modern glassmorphism UI with animated background
- URL validation (supports `watch`, `shorts`, `youtu.be`, `live`, `embed`)
- Cookie-based authentication to bypass YouTube rate limits
- Bundled `ffmpeg` via `imageio-ffmpeg` — no system install required
- Diagnostic endpoints for debugging runtime and cookie status

---

## Tech Stack

| Layer       | Technology                        |
|-------------|-----------------------------------|
| Backend     | FastAPI + Uvicorn                 |
| Downloader  | yt-dlp                            |
| Merging     | ffmpeg (bundled via imageio-ffmpeg) |
| Templates   | Jinja2                            |
| Frontend    | Vanilla HTML / CSS / JS           |
| Deployment  | Render (Nixpacks)                 |

---

## Project Structure

```
YT_Downloader/
├── app/
│   ├── main.py                  # FastAPI app, logging, lifespan hooks
│   ├── routes/
│   │   └── download.py          # API endpoints + debug routes
│   ├── services/
│   │   └── downloader.py        # yt-dlp logic, format parsing, job tracking
│   ├── utils/
│   │   ├── validator.py         # YouTube URL validation
│   │   └── file_handler.py      # Downloads dir + cookie file management
│   ├── static/                  # Static assets served at root
│   └── templates/
│       └── index.html           # UI (glassmorphism, animated background)
├── downloads/                   # Temporary video storage (auto-cleaned)
├── scripts/                     # Utility/maintenance scripts
├── cookies.txt                  # YouTube session cookies (gitignored)
├── nixpacks.toml                # Render build config (adds Node.js)
├── requirements.txt
└── README.md
```

---

## Prerequisites

- **Python 3.10+**
- **Node.js** — required by `yt-dlp` to solve YouTube's signature/n-parameter challenges

> **ffmpeg** is bundled automatically via `imageio-ffmpeg` — no manual install needed for local dev or on Render.

### Install Node.js

**Windows** — download from [nodejs.org](https://nodejs.org/)

**macOS**
```bash
brew install node
```

**Linux**
```bash
sudo apt install nodejs
```

> On **Render**, Node.js is added automatically via `nixpacks.toml`.

---

## Setup

**1. Clone the repository**
```bash
git clone <repo-url>
cd YT_Downloader
```

**2. Create and activate a virtual environment**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Add cookies (recommended)**

Export your YouTube cookies from a logged-in browser session (using a browser extension like *Get cookies.txt LOCALLY*) and place the file at the project root:

```
cookies.txt   ← Netscape/Mozilla format
```

The app loads this file automatically on startup. Without it, YouTube may rate-limit or block requests. The `cookies.txt` file is listed in `.gitignore` and will not be committed.

---

## Running the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open your browser at `http://localhost:8000`

---

## Usage

1. Paste a YouTube URL into the input field
2. Click **Check** — available quality options load with estimated file sizes
3. Select a quality card (360p → 4K)
4. Click **Download** — the server fetches, merges, and streams the video
5. The file saves automatically to your browser's Downloads folder
6. The file is deleted from the server immediately after delivery

---

## API Reference

| Method | Endpoint           | Description                                                  |
|--------|--------------------|--------------------------------------------------------------|
| `GET`  | `/`                | Serves the UI                                                |
| `GET`  | `/formats?url=...` | Returns available qualities with estimated file sizes        |
| `POST` | `/download`        | Starts a background download job, returns `job_id`           |
| `GET`  | `/status/{job_id}` | Returns job status (`pending`, `downloading`, `completed`, `failed`) |
| `GET`  | `/file/{job_id}`   | Streams the completed file to the browser, then deletes it   |
| `GET`  | `/debug`           | Diagnostic info: JS runtime, yt-dlp version, cookie status   |
| `GET`  | `/debug/test`      | Runs a live format-fetch against a known video to verify setup |

### POST /download — Request body (form)

| Field       | Type     | Default | Description                                              |
|-------------|----------|---------|----------------------------------------------------------|
| `url`       | `string` | required | YouTube video URL                                       |
| `format_id` | `string` | `best`  | Quality key: `360`, `480`, `720`, `1080`, `1440`, `2160`, `best` |

---

## Deployment (Render)

The project deploys to Render using Nixpacks. The `nixpacks.toml` at the project root adds Node.js to the build environment alongside Python:

```toml
[phases.setup]
nixPkgs = ["...", "nodejs"]
```

**Recommended Render settings:**

| Setting         | Value                                           |
|-----------------|-------------------------------------------------|
| Build Command   | `pip install -r requirements.txt`               |
| Start Command   | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

**Cookies on Render:**

Place a valid `cookies.txt` in the repository root. The app reads it from disk on startup. Since `cookies.txt` is gitignored by default, you can either:
- Temporarily remove it from `.gitignore` to commit it, or
- Use Render's **Secret Files** feature to inject it at `/etc/secrets/cookies.txt` and symlink/copy it into the project root in a build script

---

## Notes

- File sizes shown in the UI are **estimates** — YouTube does not always expose exact stream sizes in its manifest
- Videos are stored temporarily in `downloads/` and deleted immediately after the browser download completes
- Playlist URLs are not supported — single video URLs only
- If `yt-dlp` returns an HTTP 429 error, YouTube is rate-limiting the server IP. Providing fresh `cookies.txt` helps mitigate this
- The `/debug` and `/debug/test` endpoints are useful for diagnosing issues on live deployments without SSH access
