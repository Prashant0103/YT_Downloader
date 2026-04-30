#!/usr/bin/env python3
"""
Refreshes YouTube cookies via the "Get cookies.txt LOCALLY" Chrome extension.

One-time setup:
    Install "Get cookies.txt LOCALLY" from the Chrome Web Store.

Then just run:
    python scripts/refresh_cookies.py

The script opens Chrome to YouTube, waits for you to click Export
in the extension, detects the downloaded file, and saves it automatically.

Alternative (if you already have a cookies file):
    python scripts/refresh_cookies.py --from-file "C:/Users/You/Downloads/youtube.com_cookies.txt"
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

COOKIES_FILE   = Path(__file__).parent.parent / "cookies.txt"
DOWNLOADS_DIR  = Path.home() / "Downloads"
WAIT_SECONDS   = 60   # how long to wait for the export


# -- File detection -----------------------------------------------------------

def find_fresh_cookie_export(since: float) -> Path | None:
    """Return a cookies file written to Downloads after `since` (epoch seconds)."""
    patterns = [
        "youtube.com_cookies.txt",
        "www.youtube.com_cookies.txt",
        "youtube_cookies.txt",
        "*youtube*cookies*.txt",
        "*cookies*youtube*.txt",
    ]
    import glob
    for pat in patterns:
        for match in glob.glob(str(DOWNLOADS_DIR / pat)):
            p = Path(match)
            if p.stat().st_mtime >= since:
                return p
    return None


def wait_for_export() -> Path:
    """Open Chrome to YouTube, then wait for the user to export cookies."""
    start_time = time.time()

    print()
    print("  -------------------------------------------------------")
    print("  ACTION REQUIRED:")
    print("  1. Chrome will open to YouTube.")
    print("  2. Click the 'Get cookies.txt LOCALLY' extension icon.")
    print("  3. Click 'Export' - the file downloads automatically.")
    print("  4. This script will detect the file and finish.")
    print()
    print("  (Don't have the extension? Install it from Chrome Web Store:")
    print("   search 'Get cookies.txt LOCALLY')")
    print("  -------------------------------------------------------")
    print()

    # Open Chrome to YouTube
    subprocess.Popen(
        ["start", "chrome", "--new-window", "https://www.youtube.com"],
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)  # give Chrome a moment to open

    print(f"  Waiting up to {WAIT_SECONDS}s for cookies export", end="", flush=True)
    while time.time() - start_time < WAIT_SECONDS:
        found = find_fresh_cookie_export(start_time)
        if found:
            print(f"\n  Detected: {found.name}")
            return found
        time.sleep(1)
        print(".", end="", flush=True)

    print("\n  Timed out. Run again and export within 60 seconds.")
    sys.exit(1)


# -- File processing ----------------------------------------------------------

def process_cookies_file(src: Path, delete_src: bool = True) -> None:
    lines   = src.read_text(encoding="utf-8", errors="replace").splitlines()
    stamped = (
        [lines[0], f"# Refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
        + lines[1:]
    )
    count = sum(1 for l in lines if l.strip() and not l.startswith("#"))
    COOKIES_FILE.write_text("\n".join(stamped), encoding="utf-8")
    print(f"  Saved {count} cookies to {COOKIES_FILE}")

    if delete_src and src != COOKIES_FILE:
        src.unlink(missing_ok=True)
        print(f"  Cleaned up: {src.name}")


# -- Main ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh YouTube cookies")
    parser.add_argument(
        "--from-file", metavar="PATH",
        help="Path to an already-exported Netscape cookies.txt file",
    )
    args = parser.parse_args()

    print("\n-- Refreshing YouTube cookies ---------------------------")

    if args.from_file:
        src = Path(args.from_file)
        print(f"  Source: {src}")
        if not src.exists():
            print(f"  File not found: {src}")
            sys.exit(1)
        process_cookies_file(src, delete_src=False)
    else:
        src = wait_for_export()
        process_cookies_file(src, delete_src=True)

    print("\nDone! Cookies will be used on the next download request.\n")


if __name__ == "__main__":
    main()
