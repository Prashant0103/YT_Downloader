"""
Quick debug script — run with:  python debug_yt.py
Shows exactly what yt-dlp returns so we can see why formats is empty.
"""
import sys
import yt_dlp
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
URL = "https://www.youtube.com/watch?v=do7psVA1K3g"

print(f"yt-dlp version : {yt_dlp.version.__version__}")
print(f"ffmpeg path    : {FFMPEG}")
print(f"URL            : {URL}")
print("-" * 60)

ydl_opts = {
    "quiet": False,          # verbose so we see all warnings
    "no_warnings": False,
    "ffmpeg_location": FFMPEG,
    "format": "bestvideo*+bestaudio*/bestvideo+bestaudio/best",
    "ignore_no_formats_error": True,
    "extractor_args": {
        "youtube": {
            # web_creator/web/mediaconnect work without GVS PO Tokens.
            # mweb & ios now require PO tokens; tv has DRM via YT experiment.
            "player_client": ["web_creator", "web", "mediaconnect"],
        }
    },
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(URL, download=False)

formats = info.get("formats", [])
print(f"\nTotal raw formats returned: {len(formats)}")

if not formats:
    print("\n⚠️  yt-dlp returned ZERO formats. YouTube is blocking this request.")
    print("    → You need to pass real browser cookies (YOUTUBE_COOKIES env var).")
else:
    print(f"\nFirst 5 formats:")
    for f in formats[:5]:
        print(f"  id={f.get('format_id')} ext={f.get('ext')} "
              f"height={f.get('height')} vcodec={f.get('vcodec')} acodec={f.get('acodec')}")

    # Check what our parser would pick
    video_formats = [
        f for f in formats
        if f.get("height") and f.get("vcodec") and f["vcodec"] != "none"
    ]
    print(f"\nVideo-stream formats (height+vcodec): {len(video_formats)}")
    for f in video_formats[:5]:
        print(f"  id={f.get('format_id')} height={f.get('height')} "
              f"vcodec={f.get('vcodec')} acodec={f.get('acodec')}")
