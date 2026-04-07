#!/usr/bin/env python3
"""
Minimal combined viewer + usage server using raw sockets.
Avoids http.server HTTP/0.9 issues and ThreadingMixIn complexity.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import socket
from pathlib import Path
from typing import Optional

VIEWER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = VIEWER_DIR.parent.resolve()
PORT = 8765
INDEX_FILE = VIEWER_DIR / "usage.json"


def get_openclaw_usage() -> dict:
    try:
        # Try reading cached JSON first (written by cron job agent)
        if INDEX_FILE.exists():
            data = json.loads(INDEX_FILE.read_text())
            if data.get("tokens_in") or data.get("run_count"):
                return data
    except Exception:
        pass

    # Fallback: run openclaw status with short timeout
    try:
        result = subprocess.run(
            ["openclaw", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout + result.stderr

        tokens_in = tokens_out = context_pct = cost_usd = run_count = model = None

        m = re.search(r"Tokens:\s*([\d,.]+[kKmM]?)\s*in", output)
        if m:
            tokens_in = m.group(1).replace(",", "")
        m = re.search(r"Tokens:\s*[\d,.]+\s*in\s*\|\s*([\d,.]+[kKmM]?)\s*out", output)
        if m:
            tokens_out = m.group(1).replace(",", "")
        m = re.search(r"Context:\s*(\d+)%", output)
        if m:
            context_pct = int(m.group(1))
        m = re.search(r"Cost:\s*\$?([\d.]+)", output)
        if m:
            cost_usd = float(m.group(1))
        m = re.search(r"Runs:\s*(\d+)", output)
        if m:
            run_count = int(m.group(1))
        m = re.search(r"Model:\s*([^\s]+)", output)
        if m:
            model = m.group(1)

        return {
            "ok": True,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "context_pct": context_pct,
            "cost_usd": cost_usd,
            "run_count": run_count,
            "model": model,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _load_usage_json() -> dict:
    """Load usage from INDEX_FILE and inject ok=True so browser fetch never sees ok=undefined."""
    try:
        if INDEX_FILE.exists():
            data = json.loads(INDEX_FILE.read_text())
            if data.get("tokens_in") or data.get("run_count"):
                data["ok"] = True
                return data
    except Exception:
        pass
    return {"ok": False, "error": "no data"}


def serve_file(sock: socket.socket, path: str) -> bool:
    """Serve a file from viewer/ subdir or project root.
    /viewer/*         → viewer/ subdir
    /viewer/../*     → project root (doc files outside viewer/)
    Returns True if served, False if not found.
    """
    # Determine where this path maps to within PROJECT_ROOT
    if path.startswith("/viewer/"):
        # /viewer/foo → viewer/foo (inside viewer subdir)
        rel = path.replace("/viewer/", "", 1).replace("/viewer", "", 1)
        normalized = os.path.normpath("viewer/" + rel).lstrip("/")
    elif path == "/viewer":
        normalized = "viewer/index.html"
    elif path == "/":
        normalized = "viewer/index.html"
    else:
        # /SOMETHING → SOMETHING (project root)
        normalized = os.path.normpath(path).lstrip("/")
        # safety: if .. escapes project root, reject
        candidate_check = (PROJECT_ROOT / normalized).resolve()
        if not str(candidate_check).startswith(str(PROJECT_ROOT) + os.sep):
            return False

    file_path = (PROJECT_ROOT / normalized).resolve()
    # Security: must stay within PROJECT_ROOT
    if not str(file_path).startswith(str(PROJECT_ROOT) + os.sep):
        return False
    # If it resolved to a directory, serve index.html inside it
    if file_path.is_dir():
        file_path = file_path / "index.html"
    if not file_path.is_file():
        return False

    content = file_path.read_bytes()
    content_type = "text/html"
    if normalized.endswith(".js"):
        content_type = "application/javascript"
    elif normalized.endswith(".css"):
        content_type = "text/css"
    elif normalized.endswith(".json"):
        content_type = "application/json"

    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: " + content_type.encode() + b"\r\n"
        b"Content-Length: " + str(len(content)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"\r\n" + content
    )
    sock.sendall(response)
    return True


def handle_request(sock: socket.socket) -> None:
    try:
        request = sock.recv(8192).decode("utf-8", errors="replace")
        if not request:
            return

        lines = request.split("\r\n")
        if not lines:
            return

        method, raw_path, _ = lines[0].split(" ", 2)
        path = raw_path.split("?")[0].split(" ")[0]

        if method != "GET":
            sock.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return

        if path == "/usage":
            data = json.dumps(_load_usage_json()).encode()
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n"
                b"\r\n" + data
            )
            sock.sendall(response)
            return

        if serve_file(sock, path):
            return

        # 404
        body = b"404 Not Found"
        sock.sendall(
            b"HTTP/1.1 404 Not Found\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n" + body
        )
    except Exception:
        pass
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        sock.close()


def main() -> None:
    os.chdir(PROJECT_ROOT)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", PORT))
    server.listen(50)
    print(f"Viewer + usage server running at http://127.0.0.1:{PORT}/viewer/")
    print(f"Usage endpoint: http://127.0.0.1:{PORT}/usage")
    try:
        while True:
            client_sock, _ = server.accept()
            t = threading.Thread(target=handle_request, args=(client_sock,), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
