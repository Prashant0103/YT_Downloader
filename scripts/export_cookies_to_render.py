#!/usr/bin/env python3
"""
Reads cookies.txt and prints the value to paste into Render's YOUTUBE_COOKIES
environment variable.

Usage:
    python scripts/export_cookies_to_render.py
"""

import sys
from pathlib import Path

COOKIES_FILE = Path(__file__).parent.parent / "cookies.txt"

if not COOKIES_FILE.exists():
    print("cookies.txt not found.")
    print("Run this first:  python scripts/refresh_cookies.py")
    sys.exit(1)

content = COOKIES_FILE.read_text(encoding="utf-8").strip()
if not content:
    print("cookies.txt is empty. Run:  python scripts/refresh_cookies.py")
    sys.exit(1)

lines = [l for l in content.splitlines() if l.strip() and not l.startswith("#")]
print(f"\nLoaded {len(lines)} cookies from {COOKIES_FILE.name}")

print()
print("=" * 66)
print("  RENDER ENVIRONMENT VARIABLE")
print("=" * 66)
print("  Name:  YOUTUBE_COOKIES")
print()
print("  Value: copy everything between the dashes below")
print("-" * 66)
print(content)
print("-" * 66)
print()
print("Steps:")
print("  1. Render dashboard -> your service -> Environment")
print("  2. Find YOUTUBE_COOKIES (or Add Environment Variable)")
print("  3. Paste the value above (everything between the dashes)")
print("  4. Save Changes -> Render redeploys automatically")
print()
print("Cookies typically last 1-4 weeks.")
print("Re-run refresh_cookies.py + this script when downloads start failing.")
print()
