#!/usr/bin/env python3
"""
One-time YouTube OAuth2 setup for production (Render / any server platform).

How it works
------------
YouTube OAuth2 tokens last for months and auto-refresh during use -- far more
reliable than browser cookies which expire in 1-4 weeks.

Step 1  Run this script once on your local machine:
            python scripts/setup_oauth2.py

Step 2  A Google device-auth URL + short code will appear in the terminal.
        Open the URL in any browser, enter the code, and authorize with your
        Google account.

Step 3  The script encodes the token and prints the exact value to paste into
        Render -> Environment -> YOUTUBE_OAUTH2_TOKEN.

Step 4  Render redeploys automatically.  Done -- no further action needed for
        months.

Re-export an existing token (no re-auth):
            python scripts/setup_oauth2.py --export-only
"""

import base64
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# OAuth2 credentials (YouTube TV client -- embedded in yt-dlp-youtube-oauth2)
# ---------------------------------------------------------------------------
_CLIENT_ID     = '861556708454-d6dlm3lh05idd8npek18k6be8ba3oc68.apps.googleusercontent.com'
_CLIENT_SECRET = 'SboVhoG9s0rNafixCSGGKXAT'
_SCOPES        = 'https://gdata.youtube.com https://www.googleapis.com/auth/youtube'
_DEVICE_CODE_URL = 'https://www.youtube.com/o/oauth2/device/code'
_TOKEN_URL       = 'https://www.youtube.com/o/oauth2/token'

# ---------------------------------------------------------------------------
# Token cache location -- must match where yt-dlp-youtube-oauth2 reads from
# yt-dlp uses ~/.cache/yt-dlp on all platforms (Windows included)
# ---------------------------------------------------------------------------
OAUTH2_TOKEN_FILE = Path.home() / ".cache" / "yt-dlp" / "youtube-oauth2" / "token_data.json"
EXPORT_FILE       = Path(__file__).parent.parent / "oauth2_token.b64"


# ---------------------------------------------------------------------------

def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)   # error details are in the body
        except Exception:
            raise RuntimeError(f"HTTP {e.code}: {body[:200]}")


def check_deps() -> None:
    try:
        import yt_dlp_plugins.extractor.youtubeoauth  # noqa: F401
    except ImportError:
        print("yt-dlp-youtube-oauth2 not installed. Run:")
        print("  pip install yt-dlp-youtube-oauth2")
        sys.exit(1)


def do_auth() -> None:
    if OAUTH2_TOKEN_FILE.exists():
        print(f"Token already cached at:\n  {OAUTH2_TOKEN_FILE}")
        ans = input("Re-authenticate with a fresh token? [y/N]: ").strip().lower()
        if ans != "y":
            export_token()
            return
        OAUTH2_TOKEN_FILE.unlink()

    # -- Step 1: request a device code ------------------------------------
    print("\nRequesting device code from YouTube...")
    code_resp = _post_json(_DEVICE_CODE_URL, {
        "client_id":    _CLIENT_ID,
        "scope":        _SCOPES,
        "device_id":    uuid.uuid4().hex,
        "device_model": "ytlr::",
    })
    if "error" in code_resp:
        print(f"Failed to get device code: {code_resp}")
        sys.exit(1)

    verification_url = code_resp["verification_url"]
    user_code        = code_resp["user_code"]
    device_code      = code_resp["device_code"]
    interval         = int(code_resp.get("interval", 5))
    expires_in       = int(code_resp.get("expires_in", 1800))

    print()
    print("=" * 66)
    print("  ACTION REQUIRED -- do this while the script is running:")
    print()
    print(f"  1. Open  {verification_url}  in your browser")
    print(f"  2. Enter code:  {user_code}")
    print(f"  3. Sign in with your Google account and click Allow")
    print()
    print(f"  (Code expires in {expires_in // 60} minutes)")
    print("=" * 66)
    print()

    # -- Step 2: poll for authorization -----------------------------------
    deadline = time.time() + expires_in
    print("Waiting for authorization", end="", flush=True)

    while time.time() < deadline:
        time.sleep(interval)
        print(".", end="", flush=True)

        # NOTE: the correct field name is "device_code", not "code".
        # The yt-dlp-youtube-oauth2 plugin v1.0.10 has a bug where it sends
        # "code" which causes an immediate invalid_request 400 error.
        token_resp = _post_json(_TOKEN_URL, {
            "client_id":     _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "device_code":   device_code,
            "grant_type":    "urn:ietf:params:oauth:grant-type:device_code",
        })

        error = token_resp.get("error")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            print("\nDevice code expired. Run the script again.")
            sys.exit(1)
        elif error == "access_denied":
            print("\nAuthorization denied. Run the script again and click Allow.")
            sys.exit(1)
        elif error:
            print(f"\nUnexpected error: {token_resp}")
            sys.exit(1)
        else:
            # Success
            break
    else:
        print("\nTimed out waiting for authorization. Run the script again.")
        sys.exit(1)

    print("\nAuthorization successful!")

    # -- Step 3: save token in the format the plugin expects --------------
    import yt_dlp
    token_data = {
        "access_token":  token_resp["access_token"],
        "expires":       datetime.datetime.now(datetime.timezone.utc).timestamp() + token_resp["expires_in"],
        "refresh_token": token_resp["refresh_token"],
        "token_type":    token_resp["token_type"],
    }
    cache_payload = {"yt-dlp_version": yt_dlp.version.__version__, "data": token_data}

    OAUTH2_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    OAUTH2_TOKEN_FILE.write_text(json.dumps(cache_payload, indent=2), encoding="utf-8")
    print(f"Token saved to: {OAUTH2_TOKEN_FILE}")

    export_token()


def export_token() -> None:
    if not OAUTH2_TOKEN_FILE.exists():
        print(f"Token file not found: {OAUTH2_TOKEN_FILE}")
        print("Run without --export-only to authenticate first.")
        sys.exit(1)

    raw = OAUTH2_TOKEN_FILE.read_text(encoding="utf-8").strip()
    b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")

    EXPORT_FILE.write_text(b64, encoding="utf-8")

    print()
    print("=" * 66)
    print("  RENDER ENVIRONMENT VARIABLE")
    print("=" * 66)
    print(f"  Name : YOUTUBE_OAUTH2_TOKEN")
    print(f"  Value: {b64[:60]}...")
    print()
    print(f"  Full value saved to: {EXPORT_FILE}")
    print("  Open that file, copy ALL contents, paste as the value.")
    print("=" * 66)
    print()
    print("In Render dashboard:")
    print("  Environment -> Add Environment Variable")
    print("  Name:  YOUTUBE_OAUTH2_TOKEN")
    print("  Value: <paste full contents of oauth2_token.b64>")
    print("  Save Changes -> Render redeploys automatically")
    print()


# ---------------------------------------------------------------------------

def main() -> None:
    check_deps()
    if "--export-only" in sys.argv:
        export_token()
    else:
        do_auth()


if __name__ == "__main__":
    main()
