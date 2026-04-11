#!/usr/bin/env python3
"""Persistent MiniMax agent — runs openclaw agent in PTY mode, reads from stdin, writes to stdout."""
import sys
import os
import json
import subprocess
import signal
import select

# Set up environment
env = dict(os.environ)
env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
env["HOME"] = "/Users/lhaclaw"

# Start openclaw agent in PTY
proc = subprocess.Popen(
    ["/opt/homebrew/bin/openclaw", "agent", "--agent", "main"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    bufsize=1,
    universal_newlines=True
)

def write_msg(msg):
    """Send a message to the agent as JSON on a line."""
    line = json.dumps({"message": msg}) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()

def read_response():
    """Read JSON response from stdout (may span multiple lines)."""
    buf = ""
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            return None
        buf += ch
        if buf.endswith("\n"):
            try:
                return json.loads(buf.strip())
            except json.JSONDecodeError:
                # Keep reading
                pass

# Signal handler for graceful shutdown
def shutdown(signum, frame):
    proc.terminate()
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

if __name__ == "__main__":
    # Read messages from stdin, write responses to stdout
    for line in sys.stdin:
        try:
            data = json.loads(line.strip())
            msg = data.get("message", "")
            if not msg:
                continue
            
            # Send to agent
            write_msg(msg)
            
            # Read response (wait up to 60s)
            import time
            start = time.time()
            response = None
            while time.time() - start < 60:
                if select.select([proc.stdout], [], [], 0.5)[0]:
                    response = read_response()
                    if response:
                        break
                # Check if process died
                if proc.poll() is not None:
                    break
            
            if response:
                print(json.dumps({"ok": True, "response": response}), flush=True)
            else:
                print(json.dumps({"ok": False, "error": "timeout or no response"}), flush=True)
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}), flush=True)
