# YouTube Video Downloader

A clean, production-ready YouTube video downloader built with **FastAPI** and **yt-dlp**. Features a modern 3D glassmorphism UI with quality selection and automatic browser download.

---

## Features

- Download YouTube videos in best available quality
- Quality selector with estimated file sizes (360p → 4K)
- Automatic browser download after server-side processing
- Background task processing — server never blocks
- Downloaded files are auto-deleted from the server after delivery
- Modern 3D glassmorphism UI with animated background
- URL validation (supports `watch`, `shorts`, `youtu.be`, `live`, `embed`)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Downloader | yt-dlp |
| Merging | ffmpeg |
| Templates | Jinja2 |
| Frontend | Vanilla HTML / CSS / JS |

---

## Project Structure

```
youtube_video_downloader/
├── app/
│   ├── main.py                  # FastAPI app, logging, lifespan
│   ├── routes/
│   │   └── download.py          # API endpoints
│   ├── services/
│   │   └── downloader.py        # yt-dlp logic, job tracking
│   ├── utils/
│   │   ├── validator.py         # YouTube URL validation
│   │   └── file_handler.py      # Downloads directory management
│   └── templates/
│       └── index.html           # UI (glassmorphism, 3D cards)
├── downloads/                   # Temporary video storage
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Prerequisites

- **Python 3.10+**
- **ffmpeg** — required to merge separate video and audio streams for 720p and above

### Install ffmpeg

**Windows (Chocolatey)**
```bash
choco install ffmpeg
```

**Windows (manual)** — download from [ffmpeg.org](https://ffmpeg.org/download.html) and add the `bin/` folder to your system `PATH`.

**macOS**
```bash
brew install ffmpeg
```

**Linux**
```bash
sudo apt install ffmpeg
```

---

## Setup

**1. Clone the repository**
```bash
git clone <repo-url>
cd youtube_video_downloader
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
4. Click **Download** — the server downloads and merges the video
5. Once ready, the file saves automatically to your browser's Downloads folder
6. The file is deleted from the server immediately after delivery

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the UI |
| `GET` | `/formats?url=<url>` | Returns available qualities + estimated sizes |
| `POST` | `/download` | Starts background download, returns `job_id` |
| `GET` | `/status/{job_id}` | Returns job status (`pending`, `downloading`, `completed`, `failed`) |
| `GET` | `/file/{job_id}` | Streams the file to the browser, then deletes it from the server |

### POST /download — Request body (form)

| Field | Type | Default | Description |
|---|---|---|---|
| `url` | `string` | required | YouTube video URL |
| `format_id` | `string` | `best` | Quality key: `360`, `480`, `720`, `1080`, `1440`, `2160`, `best` |

---

## Notes

- File sizes shown in the UI are **estimates** — YouTube does not always expose exact stream sizes in its manifest
- Videos are stored temporarily in `downloads/` and deleted once delivered to the browser
- For best quality (1080p+), ffmpeg must be installed and available on `PATH`
- Playlist URLs are not supported — single video URLs only
