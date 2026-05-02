#!/usr/bin/env python3
"""
encode_cookies.py
-----------------
Encodes a cookies.txt file to base64 for use as the YOUTUBE_COOKIES_B64
environment variable on Render (or any other host).

Usage:
    python scripts/encode_cookies.py                   # uses cookies.txt in project root
    python scripts/encode_cookies.py path/to/cookies.txt

Steps after running:
    1. Copy the printed base64 string
    2. In Render dashboard → your service → Environment
    3. Add variable:  YOUTUBE_COOKIES_B64 = <paste here>
    4. Redeploy the service
"""

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COOKIES = ROOT / "cookies.txt"

src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_COOKIES

if not src.exists():
    print(f"ERROR: File not found: {src}")
    sys.exit(1)

content = src.read_bytes()
encoded = base64.b64encode(content).decode("ascii")

data_lines = [
    l for l in src.read_text(encoding="utf-8", errors="replace").splitlines()
    if l.strip() and not l.startswith("#")
]

print(f"\nOK  Encoded {src.name}  ({len(data_lines)} cookie entries, {len(content)} bytes)\n")
print("=" * 72)
print(encoded)
print("=" * 72)
print("\n-->  Copy the string above and set it as YOUTUBE_COOKIES_B64 in Render.\n")
