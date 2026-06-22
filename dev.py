#!/usr/bin/env python3
"""
Auto-reload dev server — watches src/*.py and restarts on any change.
No extra dependencies needed.

Usage:
    python3 dev.py
    python3 dev.py --port 9001
"""
import hashlib
import subprocess
import sys
import time
from pathlib import Path


def _hashes(src_dir: Path) -> dict:
    return {p: hashlib.md5(p.read_bytes()).hexdigest() for p in src_dir.rglob("*.py")}


def _start(port: str, profile: str) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "src.job_hunt_ui", "--profile", profile, "--port", port]
    print(f"\n▶  Starting server → http://127.0.0.1:{port}")
    return subprocess.Popen(cmd)


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Auto-reload dev server")
    p.add_argument("--port", default="9000")
    p.add_argument("--profile", default="data/mic_profile.json")
    args = p.parse_args()

    src = Path("src")
    hashes = _hashes(src)
    proc = _start(args.port, args.profile)

    print("Watching src/ for changes — Ctrl+C to stop\n")
    try:
        while True:
            time.sleep(1)
            new = _hashes(src)
            changed = [str(f) for f in new if new[f] != hashes.get(f)]
            if changed:
                print(f"Changed: {', '.join(changed)}")
                hashes = new
                proc.terminate()
                proc.wait()
                time.sleep(0.3)
                proc = _start(args.port, args.profile)
    except KeyboardInterrupt:
        print("\nStopping...")
        proc.terminate()


if __name__ == "__main__":
    main()
