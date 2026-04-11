#!/usr/bin/env python3
"""
Disconnection Diagnoser — parses gateway.err.log and gateway.log
to explain WHY disconnections happened, not just that they did.

Usage:
    python3 disconnect_diagnosis.py              # last 10 disconnections
    python3 disconnect_diagnosis.py --count 20  # last 20 events
    python3 disconnect_diagnosis.py --watch     # tail -f style monitoring
"""

import re
import sys
import argparse
from datetime import datetime
from pathlib import Path

GATEWAY_ERR = Path("/Users/lhaclaw/.openclaw/logs/gateway.err.log")
GATEWAY_LOG = Path("/Users/lhaclaw/.openclaw/logs/gateway.log")

# ─── Categorize root causes ────────────────────────────────────────────────────

CATEGORIES = {
    "INTENTIONAL_RESTART":  "Intentional — gateway restart (SIGTERM/SIGINT received, config change, or manual stop)",
    "NETWORK":              "Network — internet connectivity issue (ENETUNREACH, timeout, DNS failure)",
    "MODEL_ERROR":          "AI model error — LLM request failed, overloaded, or connection error",
    "MODEL_TIMEOUT":        "AI model timeout — LLM request timed out (MiniMax or Codex)",
    "CONTEXT_OVERFLOW":     "Context overflow — session grew too large for the model context window",
    "CONFIG_ERROR":         "Config error — invalid config caused reload failure or skip",
    "OOM":                  "Out of memory — process was killed by system OOM",
    "Tailscale":            "Tailscale — remote connection dropped or unavailable",
    "BONJOUR":              "Bonjour/mDNS — local service advertisement issue",
    "HOOK_PLUGIN":          "Hook/plugin error — managed hook or plugin caused an exception",
    "TELEGRAM":             "Telegram — Telegram API connectivity issue",
    "SUBAGENT":             "Subagent — orphan run pruned or subagent session error",
    "UNKNOWN":              "Unknown — no matching pattern found",
}

# Patterns checked in ORDER — first match wins
PATTERNS = [
    # INTENTIONAL
    (r"signal SIG\w+ received",                                     "INTENTIONAL_RESTART"),
    (r"shutting down",                                               "INTENTIONAL_RESTART"),
    (r"config change requires gateway restart",                      "INTENTIONAL_RESTART"),
    (r"gateway stopping",                                             "INTENTIONAL_RESTART"),
    (r"disconnected code=1012 reason=service restart",              "INTENTIONAL_RESTART"),

    # CONTEXT OVERFLOW
    (r"context overflow",                                             "CONTEXT_OVERFLOW"),
    (r"Context overflow",                                            "CONTEXT_OVERFLOW"),
    (r"context.*exceed",                                              "CONTEXT_OVERFLOW"),

    # MODEL TIMEOUT
    (r"LLM request timed out",                                       "MODEL_TIMEOUT"),
    (r"model.*timeout",                                              "MODEL_TIMEOUT"),
    (r"timeout.*model",                                              "MODEL_TIMEOUT"),
    (r"TimeoutError.*aborted.*timeout",                              "MODEL_TIMEOUT"),

    # MODEL ERROR
    (r"LLM request failed.*network connection error",                "MODEL_ERROR"),
    (r"rawError=Connection error",                                    "MODEL_ERROR"),
    (r"rawError=529.*overloaded",                                    "MODEL_ERROR"),
    (r"The AI service is temporarily overloaded",                    "MODEL_ERROR"),
    (r"pricing bootstrap failed",                                    "MODEL_ERROR"),
    (r"FailoverError",                                               "MODEL_ERROR"),
    (r"model fallback decision: decision=candidate_failed",           "MODEL_ERROR"),

    # NETWORK
    (r"ENETUNREACH",                                                 "NETWORK"),
    (r"ECONNREFUSED",                                                "NETWORK"),
    (r"ETIMEDOUT",                                                   "NETWORK"),
    (r"DNS-resolved IP unreachable",                                "NETWORK"),
    (r"fetch fallback",                                               "NETWORK"),
    (r"webhook cleanup failed.*Network request",                      "NETWORK"),
    (r"deleteWebhook failed.*Network request",                        "NETWORK"),

    # CONFIG ERROR
    (r"config reload skipped.*invalid config",                        "CONFIG_ERROR"),
    (r"Unrecognized key",                                            "CONFIG_ERROR"),
    (r"Could not find edits\[\d+\] in.*oldText must match exactly",  "CONFIG_ERROR"),

    # OOM
    (r"OOM|out of memory|killed.*memory",                            "OOM"),

    # Tailscale
    (r"tailscale.*unreachable|tailscale.*fail",                      "Tailscale"),
    (r"WS via wss://.*\.taila1eac0\.ts\.net",                       "Tailscale"),

    # TELEGRAM
    (r"telegram.*timeout|telegram.*fail|telegram.*unreachable",      "TELEGRAM"),

    # BONJOUR
    (r"bonjour.*watchdog|bonjour.*non-announced",                    "BONJOUR"),

    # SUBAGENT
    (r"orphan run pruned|subagent.*error|subagent.*fail",             "SUBAGENT"),

    # LANE WAIT (upstream of timeouts)
    (r"lane wait exceeded",                                             "LANE_WAIT"),

    # MODEL FALLBACK (upstream of disconnects)
    (r"model fallback decision",                                        "MODEL_FALLBACK"),

    # HOOK/PLUGIN
    (r"hook.*error|hook.*fail|Uncaught exception.*hook",             "HOOK_PLUGIN"),
]


def categorize(line: str) -> str:
    for pattern, category in PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return category
    return "UNKNOWN"


def extract_context(lines: list[str], idx: int, before: int = 3, after: int = 2) -> list[str]:
    """Get surrounding lines for context."""
    start = max(0, idx - before)
    end = min(len(lines), idx + after + 1)
    return lines[start:end]


def parse_timestamp(line: str) -> str | None:
    """Extract ISO timestamp from log line."""
    m = re.search(r"(\d{4}-\d{2}-\d{2}T[\d:.]+[+-]\d{2}:\d{2})", line)
    return m.group(1) if m else None


def format_ts(ts: str) -> str:
    """Format ISO timestamp to HH:MM:SS."""
    if not ts:
        return "??:??"
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except Exception:
        return ts[11:19] if len(ts) > 11 else ts[:8]

def analyze_gateway_err(err_lines: list[str], count: int) -> list[dict]:
    """Find disconnection-related entries in gateway.err.log."""
    results = []

    # Noise patterns to skip entirely
    skip_substrings = [
        "sqlite-vec unavailable",
        "vector embeddings",
        "chunks written for",
        "chunks_vec not updated",
        "[hooks:loader] Hook",
        "[hooks:loader] Loading managed hook",
        "internal hook handlers",
        "embedded acpx runtime backend",
        "plugin.*registered|plugin.*ready",
    ]
    skip_re = re.compile(
        "|".join(re.escape(s) for s in skip_substrings),
        re.IGNORECASE
    )

    for i, line in enumerate(err_lines):
        if skip_re.search(line):
            continue

        ts = parse_timestamp(line) or ""
        cat = categorize(line)

        # Get context lines
        context = extract_context(err_lines, i)

        results.append({
            "timestamp": ts,
            "ts_human": format_ts(ts),
            "category": cat,
            "category_desc": CATEGORIES.get(cat, "Unknown"),
            "line": line.strip(),
            "context": [l.strip() for l in context if l.strip() and not skip_re.search(l)],
        })

    # Merge consecutive entries of same category within 30s
    merged = []
    for r in results:
        if merged and merged[-1]["category"] == r["category"]:
            prev_ts = merged[-1]["timestamp"]
            if prev_ts and r["timestamp"]:
                try:
                    prev_dt = datetime.fromisoformat(prev_ts)
                    cur_dt = datetime.fromisoformat(r["timestamp"])
                    if (cur_dt - prev_dt).total_seconds() < 30:
                        merged[-1]["context"] = merged[-1]["context"] + r["context"]
                        continue
                except Exception:
                    pass
        merged.append(r)

    return merged[-count:]


def analyze_gateway_log(log_lines: list[str], count: int) -> list[dict]:
    """Find disconnect/reconnect events in gateway.log."""
    results = []
    disconnect_pattern = re.compile(r"disconnected|disconnect|reconnecting|reconnect", re.IGNORECASE)
    restart_pattern = re.compile(r"starting\.\.\.|shutting down|signal SIG|ready \(|gateway stopping", re.IGNORECASE)

    for i, line in enumerate(log_lines):
        if not (disconnect_pattern.search(line) or restart_pattern.search(line)):
            continue
        ts = parse_timestamp(line) or ""
        context = extract_context(log_lines, i, before=1, after=1)
        results.append({
            "timestamp": ts,
            "ts_human": format_ts(ts),
            "category": "DISCONNECT_EVENT",
            "category_desc": "Gateway connection event",
            "line": line.strip(),
            "context": [l.strip() for l in context if l.strip()],
        })

    return results[-count:]


def main():
    parser = argparse.ArgumentParser(description="Diagnose OpenClaw disconnection reasons")
    parser.add_argument("--count", "-n", type=int, default=10, help="Number of events to show (default: 10)")
    parser.add_argument("--err-only", action="store_true", help="Only show gateway.err.log")
    parser.add_argument("--log-only", action="store_true", help="Only show gateway.log disconnect events")
    args = parser.parse_args()

    err_lines = GATEWAY_ERR.read_text().splitlines() if GATEWAY_ERR.exists() else []
    log_lines = GATEWAY_LOG.read_text().splitlines() if GATEWAY_LOG.exists() else []

    print(f"╔══════════════════════════════════════════════════════════════╗")
    print(f"║       OpenClaw Disconnection Diagnoser                      ║")
    print(f"║       {datetime.now().strftime('%Y-%m-%d %H:%M')}  ({len(err_lines)} err lines / {len(log_lines)} log lines)    ║")
    print(f"╚══════════════════════════════════════════════════════════════╝\n")

    events = []

    if not args.log_only:
        err_events = analyze_gateway_err(err_lines, args.count)
        events.extend(err_events)

    if not args.err_only:
        log_events = analyze_gateway_log(log_lines, args.count)
        events.extend(log_events)

    # Sort by timestamp descending
    events.sort(key=lambda x: x["timestamp"] or "", reverse=True)

    # Deduplicate — prefer the more detailed err entry if log entry is redundant
    shown_lines = set()
    unique_events = []
    for e in events:
        first_line = e["context"][0] if e["context"] else e["line"]
        # Skip very short/noise lines
        if len(first_line) < 20:
            continue
        if first_line in shown_lines and e["category"] == "DISCONNECT_EVENT":
            continue
        shown_lines.add(first_line)
        unique_events.append(e)

    if not unique_events:
        print("No significant events found in the logs.")
        return

    # Deduplicate by first context line
    shown = set()
    unique_events2 = []
    for e in unique_events:
        key = e["context"][0] if e.get("context") else e["line"][:80]
        if key not in shown:
            shown.add(key)
            unique_events2.append(e)

    if not unique_events2:
        print("No significant events found in the logs.")
        return

    cat_emoji = {
        "INTENTIONAL_RESTART": "🟢",
        "NETWORK": "🔴",
        "MODEL_ERROR": "🔴",
        "MODEL_TIMEOUT": "🔴",
        "CONTEXT_OVERFLOW": "🟡",
        "CONFIG_ERROR": "🟡",
        "OOM": "🔴",
        "Tailscale": "🟠",
        "BONJOUR": "🟡",
        "HOOK_PLUGIN": "🔴",
        "TELEGRAM": "🟠",
        "SUBAGENT": "🟡",
        "DISCONNECT_EVENT": "⚪",
        "LANE_WAIT": "🟡",
        "MODEL_FALLBACK": "🔴",
        "UNKNOWN": "⚪",
    }

    for e in unique_events2[:args.count]:
        cat = e["category"]
        emoji = cat_emoji.get(cat, "⚪")
        ts = e["ts_human"] or "??:??:??"

        print(f"{emoji} [{ts}] {e['category_desc']}")
        print(f"   {e['line'][:120]}")
        if e.get("context") and len(e["context"]) > 1:
            shown_ctx = 0
            for ctx in e["context"][1:]:
                if ctx != e["line"] and len(ctx) > 20 and shown_ctx < 3:
                    print(f"   └ {ctx[:120]}")
                    shown_ctx += 1
        print()

    print("─── Category Key ─────────────────────────────────────────────")
    print("🟢 Intentional   🔴 Network/Error   🟡 Warning   🟠 Telegram/Tailscale")


if __name__ == "__main__":
    main()
