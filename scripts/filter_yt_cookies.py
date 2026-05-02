#!/usr/bin/env python3
"""
filter_yt_cookies.py
--------------------
Strips a full browser export cookies.txt down to only the YouTube/Google
authentication cookies that yt-dlp actually needs. Reduces a 1000+ line
export to ~20 lines, making it small enough to paste as an env var.

Usage:
    python scripts/filter_yt_cookies.py
    python scripts/filter_yt_cookies.py path/to/cookies.txt

Output files:
    cookies_yt_only.txt     -- filtered plaintext (commit or use as file)
    cookies_yt_only.b64     -- base64-encoded version for YOUTUBE_COOKIES_B64
"""

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cookies.txt"
OUT_TXT = ROOT / "cookies_yt_only.txt"
OUT_B64 = ROOT / "cookies_yt_only.b64"

# Only these domains matter for YouTube authentication
KEEP_DOMAINS = {
    ".youtube.com",
    "youtube.com",
    ".google.com",
    "accounts.google.com",
    ".google.co.in",   # adjust if you're in a different country (e.g. .google.co.uk)
}

# The specific cookie names yt-dlp uses for authentication and identity.
# Keeping ONLY these reduces noise and avoids sending irrelevant auth tokens.
KEEP_NAMES = {
    # YouTube session tokens
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "SIDCC",
    # YouTube visitor / player tokens
    "VISITOR_INFO1_LIVE",
    "VISITOR_PRIVACY_METADATA",
    "__Secure-ROLLOUT_TOKEN",
    "PREF",
    "GPS",
    "YSC",
    "SOCS",
    # Google account identity (needed for age-restricted videos)
    "NID",
    "__Secure-1PSIDRTS",
    "__Secure-3PSIDRTS",
}

if not SRC.exists():
    print(f"ERROR: {SRC} not found")
    sys.exit(1)

lines_in = SRC.read_text(encoding="utf-8", errors="replace").splitlines()
kept = []
skipped = 0

for line in lines_in:
    # Always keep header comments
    if line.startswith("#") or not line.strip():
        kept.append(line)
        continue

    parts = line.split("\t")
    if len(parts) < 7:
        skipped += 1
        continue

    domain = parts[0]
    name   = parts[5]

    if domain in KEEP_DOMAINS and name in KEEP_NAMES:
        kept.append(line)
    else:
        skipped += 1

content = "\n".join(kept) + "\n"
data_lines = [l for l in kept if l.strip() and not l.startswith("#")]

OUT_TXT.write_text(content, encoding="utf-8")
encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
OUT_B64.write_text(encoded, encoding="utf-8")

print(f"\nSource : {SRC}  ({len(lines_in)} lines)")
print(f"Kept   : {len(data_lines)} cookie entries")
print(f"Skipped: {skipped} irrelevant entries")
print(f"\nOutput files written:")
print(f"  {OUT_TXT}  (use as cookies.txt or Render Secret File)")
print(f"  {OUT_B64}  (paste as YOUTUBE_COOKIES_B64 env var)\n")
print("=" * 72)
print(f"YOUTUBE_COOKIES_B64 value ({len(encoded)} chars):")
print("=" * 72)
print(encoded)
print("=" * 72)
print("\n-->  Copy the string above into Render > Environment > YOUTUBE_COOKIES_B64\n")
