#!/usr/bin/env python3
"""
Registers a Windows Task Scheduler job that runs refresh_cookies.py every Monday at 9 AM.

Usage:
    python scripts/schedule_task.py          # create / update task
    python scripts/schedule_task.py --remove  # delete task
    python scripts/schedule_task.py --run     # run immediately
"""

import argparse
import subprocess
import sys
from pathlib import Path

TASK_NAME  = "YT Downloader - Weekly Cookie Refresh"
SCRIPT     = Path(__file__).parent / "refresh_cookies.py"
PYTHON     = sys.executable          # same interpreter running this script
SCHEDULE   = "weekly"
DAY        = "MON"
START_TIME = "09:00"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def create_task() -> None:
    cmd = [
        "schtasks", "/create",
        "/tn",  TASK_NAME,
        "/tr",  f'"{PYTHON}" "{SCRIPT}" --browser firefox',
        "/sc",  SCHEDULE,
        "/d",   DAY,
        "/st",  START_TIME,
        "/rl",  "HIGHEST",   # run with highest privileges
        "/f",                # overwrite if already exists
    ]
    res = run(cmd)
    if res.returncode == 0:
        print(f"✓ Task created: '{TASK_NAME}'")
        print(f"  Runs every {DAY} at {START_TIME}")
        print(f"  Script: {SCRIPT}")
        print(f"  Python: {PYTHON}")
    else:
        print(f"✗ Failed to create task:\n  {res.stderr.strip()}")
        print("\nTry running this script as Administrator.")
        sys.exit(1)


def remove_task() -> None:
    res = run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
    if res.returncode == 0:
        print(f"✓ Task removed: '{TASK_NAME}'")
    else:
        print(f"✗ Failed: {res.stderr.strip()}")
        sys.exit(1)


def run_task_now() -> None:
    res = run(["schtasks", "/run", "/tn", TASK_NAME])
    if res.returncode == 0:
        print(f"✓ Task triggered manually: '{TASK_NAME}'")
    else:
        print(f"✗ Failed: {res.stderr.strip()}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the cookie refresh scheduled task")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", action="store_true", help="Delete the scheduled task")
    group.add_argument("--run",    action="store_true", help="Trigger the task immediately")
    args = parser.parse_args()

    if args.remove:
        remove_task()
    elif args.run:
        run_task_now()
    else:
        create_task()


if __name__ == "__main__":
    main()
