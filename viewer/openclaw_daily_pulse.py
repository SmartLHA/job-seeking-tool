#!/usr/bin/env python3
"""
OpenClaw Daily Pulse — 社群情報報告
掃描 GitHub、Reddit OpenClaw 生態系統信號。
每日 Cron 運行（倫敦 9AM）。輸出：openclaw_daily_pulse.json
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error

# ─── Config ────────────────────────────────────────────────────────────────────
OUTPUT_FILE = Path.home() / ".openclaw" / "workspace" / "viewer" / "openclaw_daily_pulse.json"
STATE_FILE = Path.home() / ".openclaw" / "workspace" / "viewer" / "openclaw_daily_pulse_state.json"
MAX_ITEMS_PER_SOURCE = 15
MAX_AGE_DAYS = 5

GH_REPOS = [
    ("openclaw_core", "openclaw/openclaw"),
    ("clawhub", "openclaw/clawhub"),
    ("openclaw_hub", "openclaw-community/openclaw-hub"),
]
GH_DISCUSSIONS_REPO = "openclaw-community/openclaw-hub"

# Reddit sources
REDDIT_SEARCH_URL = "https://www.reddit.com/search.json?q=openclaw+ai+agent&sort=new&limit=15"
REDDIT_USE_CASES_URL = "https://www.reddit.com/r/openclaw/search.json?q=flair_name%3A%22Use%20Cases%22&sort=top&limit=15&restrict_sr=1"
REDDIT_HOT_URL = "https://www.reddit.com/r/openclaw/hot.json?limit=15"

CUSTOM_USER_AGENT = "Mozilla/5.0 (compatible; OpenClaw-DailyPulse/1.0)"


def gh_headers() -> dict:
    token = None
    cred_file = Path.home() / ".openclaw" / "credentials" / "github.json"
    if cred_file.exists():
        try:
            token = json.loads(cred_file.read_text()).get("token")
        except Exception:
            pass
    h = {"User-Agent": CUSTOM_USER_AGENT, "Accept": "application/vnd.github.v3+json"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def fetch(url: str, headers: dict | None = None, timeout: int = 10) -> str | None:
    h = headers or {"User-Agent": CUSTOM_USER_AGENT}
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def gh_graphql_query(query: str, headers: dict) -> dict | None:
    try:
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query}).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception:
        return None


def parse_gh_issues(raw: str, skip_date_filter: bool = False) -> list[dict]:
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    results = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    for item in items:
        if isinstance(item, dict) and "pull_request" in item:
            continue
        created = item.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)
        if not skip_date_filter and dt < cutoff:
            continue
        results.append({
            "source": "github_issues",
            "title": item.get("title", ""),
            "url": item.get("html_url", ""),
            "labels": [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)],
            "comments": item.get("comments", 0),
            "created": created[:10],
            "body_preview": (item.get("body") or "")[:300],
        })
    return results


def parse_gh_discussions(graphql_data: dict | None) -> list[dict]:
    if not graphql_data:
        return []
    results = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    try:
        nodes = graphql_data.get("data", {}).get("repository", {}).get("discussions", {}).get("nodes", [])
    except Exception:
        return []
    for d in nodes:
        created = d.get("createdAt", "")
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)
        if dt < cutoff:
            continue
        results.append({
            "source": "github_discussions",
            "title": d.get("title", ""),
            "url": d.get("url", ""),
            "category": d.get("category", {}).get("name", ""),
            "comments": d.get("comments", {}).get("totalCount", 0),
            "created": created[:10],
            "body_preview": (d.get("body") or "")[:300],
        })
    return results


def parse_reddit(raw: str, source_type: str = "reddit") -> list[dict]:
    try:
        data = json.loads(raw)
    except Exception:
        return []
    results = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    children = data.get("data", {}).get("children", [])
    for child in children[:MAX_ITEMS_PER_SOURCE]:
        post = child.get("data", {})
        created_utc = post.get("created_utc", 0)
        dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        if dt < cutoff:
            continue
        results.append({
            "source": source_type,
            "title": post.get("title", ""),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "subreddit": post.get("subreddit", ""),
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "created": dt.strftime("%Y-%m-%d"),
            "body_preview": (post.get("selftext") or "")[:300],
            "is_self": post.get("is_self", True),
            "link_flair_text": post.get("link_flair_text", ""),
        })
    return results


def parse_reddit_use_cases(raw: str) -> list[dict]:
    """Parse Reddit search results for Use Cases flair."""
    try:
        data = json.loads(raw)
    except Exception:
        return []
    results = []
    children = data.get("data", {}).get("children", [])
    for child in children[:20]:  # Get more for use cases
        post = child.get("data", {})
        results.append({
            "source": "reddit_use_cases",
            "title": post.get("title", ""),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "subreddit": "openclaw",
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "created": datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc).strftime("%Y-%m-%d"),
            "body_preview": (post.get("selftext") or "")[:500],
            "is_self": post.get("is_self", True),
            "link_flair_text": post.get("link_flair_text", "Use Cases"),
        })
    return results


def categorize_item(item: dict) -> str:
    title = (item.get("title") or "").lower()
    body = (item.get("body_preview") or "").lower()
    text = title + " " + body
    labels = item.get("labels", [])
    source = item.get("source", "")
    flair = item.get("link_flair_text", "")

    spam_kw = ["notebooklm", "omniroute", "aitx", "rad inc", "depins", "defi yield", "nfts", "pump.fun",
               "free followers", "dm me", "link in bio", "subscribe to", "my newsletter",
               "shill", "moonshot", "10x", "100x", "to the moon", "wen launch", "presale"]
    critical_kw = ["cve-", "security vulnerability", "data corruption", "memory leak",
                   "segfault", "panic", "remote code execution", "0-day", "0day"]
    bug_kw = ["bug", "crash", "broken", "cannot", "unable to", "doesn't work",
              "fails to", "error:", "issue:", "regression", "[bug]"]
    discussion_kw = ["discuss", "opinion", "debate", "architecture", "approach", "thoughts",
                     "consider", "feedback", "rfc"]
    best_practice_kw = ["best practice", "setup guide", "how to", "tip:", "workflow",
                        "optimize", "config example", "pattern:", "template:", "guide"]
    risk_kw = ["warning:", "breaking change", "deprecate", "risk", "concern",
               "security harden", "exploit", "injection", "prompt injection", "unauthorized"]
    failure_kw = ["fail:", "failed:", "bug report", "went wrong", "unexpected behavior",
                  "doesn't start", "broken after"]
    use_case_kw = ["use case", "showcase", "workflow", "automation", "setup", "personal assistant",
                   "saved me", "made me", "passive income", "literally made me", "i've been using",
                   "workflow", "integration"]

    if source in ("reddit_use_cases", "reddit_hot"):
        return "use_cases"

    if source == "github_issues":
        if any(kw in text for kw in critical_kw):
            return "critical"
        if "enhancement" in labels or any(l.startswith("feat") for l in labels):
            return "features"
        if any(kw in text for kw in bug_kw):
            return "issues"
        return "general"

    elif source == "github_discussions":
        if any(kw in text for kw in critical_kw):
            return "critical"
        if any(kw in text for kw in discussion_kw):
            return "discussions"
        if any(kw in text for kw in risk_kw):
            return "risks"
        return "general"

    elif source == "reddit":
        if any(kw in text for kw in spam_kw):
            return "general"
        if any(kw in text for kw in critical_kw):
            return "critical"
        if any(kw in text for kw in risk_kw):
            return "risks"
        if any(kw in text for kw in best_practice_kw):
            return "best_practices"
        if any(kw in text for kw in failure_kw):
            return "failures"
        return "general"

    return "general"


def load_previous_report() -> dict | None:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return None


def save_state(report: dict) -> None:
    STATE_FILE.write_text(json.dumps(report, indent=2))


def build_report(gh_issues: list, gh_discussions: list, reddit: list,
                 reddit_use_cases: list, reddit_hot: list,
                 has_discussions: bool = True) -> dict:
    prev = load_previous_report()
    prev_titles = {i["title"] + i.get("repo", "") for i in prev.get("all_gh_issues", [])} if prev else set()
    prev_disc = {d["title"] for d in prev.get("all_gh_discussions", [])} if prev else set()
    prev_reddit = {r["title"] for r in prev.get("all_reddit", [])} if prev else set()
    prev_uc = {r["title"] for r in prev.get("all_reddit_use_cases", [])} if prev else set()

    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    def tag_new(item, prev_set):
        item["is_new"] = item["title"] not in prev_set
        return item

    gh_issues = [tag_new(i, prev_titles) for i in gh_issues]
    gh_discussions = [tag_new(d, prev_disc) for d in gh_discussions]
    reddit = [tag_new(r, prev_reddit) for r in reddit]
    reddit_use_cases = [tag_new(r, prev_uc) for r in reddit_use_cases]
    reddit_hot = [tag_new(r, prev_reddit) for r in reddit_hot]

    all_items = gh_issues + gh_discussions + reddit + reddit_use_cases + reddit_hot

    sections = {"critical": [], "issues": [], "features": [], "discussions": [],
                "best_practices": [], "risks": [], "failures": [], "use_cases": [], "general": []}
    for item in all_items:
        cat = categorize_item(item)
        item["category"] = cat
        sections[cat].append(item)

    def issue_sort_key(x):
        comments = x.get("comments") or 0
        return (-comments, not x.get("is_new", True))

    def default_sort_key(x):
        score = x.get("comments") or x.get("score") or 0
        return (not x.get("is_new", True), -score)

    def use_case_sort_key(x):
        score = x.get("score") or 0
        return (-score, not x.get("is_new", True))

    sections["issues"].sort(key=issue_sort_key)
    sections["use_cases"].sort(key=use_case_sort_key)
    for cat in ["critical", "features", "discussions", "best_practices", "risks", "failures", "general"]:
        sections[cat].sort(key=default_sort_key)

    return {
        "generated_at": now,
        "_has_discussions": has_discussions,
        "summary": {
            "total_items": len(all_items),
            "new_items": sum(1 for i in all_items if i.get("is_new")),
            "gh_issues": len(gh_issues),
            "gh_discussions": len(gh_discussions),
            "reddit": len(reddit),
            "reddit_use_cases": len(reddit_use_cases),
            "reddit_hot": len(reddit_hot),
            "critical_count": len(sections["critical"]),
            "issues_count": len(sections["issues"]),
            "features_count": len(sections["features"]),
            "discussions_count": len(sections["discussions"]),
            "use_cases_count": len(sections["use_cases"]),
        },
        "all_items": all_items,
        "all_gh_issues": gh_issues,
        "all_gh_discussions": gh_discussions,
        "all_reddit": reddit,
        "all_reddit_use_cases": reddit_use_cases,
        "all_reddit_hot": reddit_hot,
    }


def format_markdown(report: dict) -> str:
    s = report["summary"]
    has_disq = report.get("_has_discussions", True)
    disc = "討論已停用" if not has_disq else f"{s.get('gh_discussions', 0)} 討論"
    total = s.get("total_items", 0)
    new_count = s.get("new_items", 0)

    all_items = report.get("all_items", [])
    critical = [i for i in all_items if i.get("category") == "critical"]
    issues = [i for i in all_items if i.get("category") == "issues"]
    features = [i for i in all_items if i.get("category") == "features"]
    general = [i for i in all_items if i.get("category") == "general"]
    use_cases = [i for i in all_items if i.get("category") == "use_cases"]

    lines = [
        f"# 🦞 OpenClaw 每日情報",
        f"*產生時間：{report['generated_at']}*",
        f"",
        f"**來源：** {s.get('gh_issues', 0)} GitHub issues · {disc} · {s.get('reddit', 0)} Reddit 帖子 · {s.get('reddit_use_cases', 0)} Use Cases · {s.get('reddit_hot', 0)} 熱門討論",
        f"**總信號數：** {total}（自上次運行以來 {new_count} 個新）",
        f"",
        f"---",
        f"",
    ]

    # ── Use Cases & Hot Topics ────────────────────────────────
    if use_cases:
        lines.append("## 🔥 Use Cases 與熱門話題")
        lines.append("")
        lines.append("| 標題 | 讚數 | 評論 | source |")
        lines.append("|------|------|------|--------|")
        for item in use_cases[:10]:
            title = item["title"][:70] + ("..." if len(item["title"]) > 70 else "")
            score = item.get("score", 0)
            comments = item.get("num_comments", 0)
            url = item.get("url", "")
            source_label = item.get("source", "").replace("reddit_use_cases", "r/openclaw Use Cases").replace("reddit_hot", "r/openclaw 熱門")
            lines.append(f"| [{title}]({url}) | {score} | {comments} | {source_label} |")
        lines.append("")

    # ── Highlights ────────────────────────────────────────────
    lines.append("## 🎯 重點速覽")
    lines.append("")

    sorted_issues = sorted(issues, key=lambda x: -(x.get("comments") or 0))
    relevant_issues = [i for i in sorted_issues if any(x in i["title"].lower() for x in
                          ["doctor", "truncat", "config", "startup", "memory", "context overflow", "skill", "workspace"])]
    commented_issues = [i for i in sorted_issues if i.get("comments", 0) > 0]
    zero_comment_issues = [i for i in sorted_issues if i.get("comments", 0) == 0 and i not in relevant_issues]

    if critical:
        for item in critical[:5]:
            repo = item.get("repo", "").replace("openclaw_core", "core")
            sub = item.get("subreddit", "")
            if not repo and not sub:
                continue
            source = f"r/{sub}" if sub else repo
            url = item.get("url", "")
            lines.append(f"• 🚨 [{item['title'][:90]}]({url}) [{source}]")
    if relevant_issues:
        lines.append(f"**⚠️ 配置相關問題（{len(relevant_issues)}）：**")
        for item in relevant_issues[:5]:
            repo = item.get("repo", "").replace("openclaw_core", "core")
            url = item.get("url", "")
            cmt = item.get("comments", 0)
            cmt_str = f" 💬{cmt}" if cmt else ""
            lines.append(f"• [{item['title'][:85]}]({url}){cmt_str}")
        lines.append("")
    if commented_issues:
        shown = [i for i in commented_issues if i not in relevant_issues][:5]
        if shown:
            lines.append(f"**🐛 最受關注的 Bug（{len(shown)}）：**")
            for item in shown:
                repo = item.get("repo", "").replace("openclaw_core", "core")
                url = item.get("url", "")
                cmt = item.get("comments", 0)
                lines.append(f"• [{item['title'][:80]}]({url}) [{repo}] 💬{cmt}")
            lines.append("")
    if zero_comment_issues:
        shown = zero_comment_issues[:3]
        lines.append(f"**🆕 新 Bug（{len(shown)} / {len(zero_comment_issues)} 無回覆）：**")
        for item in shown:
            repo = item.get("repo", "").replace("openclaw_core", "core")
            url = item.get("url", "")
            lines.append(f"• [{item['title'][:80]}]({url}) [{repo}]")
        lines.append("")
    if features:
        relevant_feats = [f for f in features if any(x in f["title"].lower() for x in
                          ["octopus", "timeout", "lightweight", "context mode", "allowlist", "subagent", "slash", "skill", "agent"])]
        lines.append(f"**💡 新功能（{len(features)} — {len(relevant_feats)} 相關）：**")
        for item in features[:8]:
            url = item.get("url", "")
            tag = " ✅" if item in relevant_feats else ""
            lines.append(f"• [{item['title'][:80]}]({url}){tag}")
        lines.append("")
    if general:
        lines.append(f"**📌 一般討論（{len(general)} 項）：**")
        for item in general[:3]:
            url = item.get("url", "")
            sub = item.get("subreddit", "") or item.get("repo", "")
            lines.append(f"• [{item['title'][:70]}]({url}) [r/{sub}]")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── Bug Reports Table ─────────────────────────────────────
    if issues:
        lines.append(f"## 🐛 Bug 回報（{len(issues)}）")
        lines.append("")
        lines.append("| # | Bug | Repo | 影響 |")
        lines.append("|---|-----|------|------|")
        for item in issues[:10]:
            num = item.get("url", "").split("/")[-1]
            title = item["title"][:65] + ("..." if len(item["title"]) > 65 else "")
            repo = item.get("repo", "").replace("openclaw_core", "core").replace("clawhub", "clawhub")
            cmt = item.get("comments", 0)
            cmt_str = f" 💬{cmt}" if cmt else ""
            url = item.get("url", "")
            tag = "⚠️ 配置" if any(x in item["title"].lower() for x in ["config", "memory", "context", "skill"]) else "🟡 一般"
            lines.append(f"| [{num}]({url}) | {title} | {repo}{cmt_str} | {tag} |")
        lines.append("")

    # ── Features Table ──────────────────────────────────────────
    if features:
        lines.append(f"## 💡 功能與改進（{len(features)}）")
        lines.append("")
        lines.append("| # | 功能 | 關鍵 |")
        lines.append("|---|---------|-----|")
        for item in features[:10]:
            num = item.get("url", "").split("/")[-1]
            title = item["title"][:60] + ("..." if len(item["title"]) > 60 else "")
            url = item.get("url", "")
            is_relevant = any(x in item["title"].lower() for x in
                             ["octopus", "timeout", "lightweight", "context mode", "allowlist", "subagent", "slash", "skill"])
            key = "✅ 相關" if is_relevant else "🟡 觀察"
            lines.append(f"| [{num}]({url}) | {title} | {key} |")
        lines.append("")

    # ── General Table ───────────────────────────────────────────
    if general:
        lines.append(f"## 📌 一般討論（{len(general)} 項）")
        lines.append("")
        lines.append("| 標題 | 來源 |")
        lines.append("|------|--------|")
        for item in general[:8]:
            title = item["title"][:60] + ("..." if len(item["title"]) > 60 else "")
            sub = item.get("subreddit", "") or item.get("repo", "")
            url = item.get("url", "")
            lines.append(f"| [{title}]({url}) | {sub} |")
        lines.append("")

    lines.append("---")
    lines.append(f"*掃描範圍：{s.get('gh_issues', 0)} GitHub issues · {disc} · {s.get('reddit', 0)} Reddit 帖子 · {s.get('reddit_use_cases', 0)} Use Cases · {s.get('reddit_hot', 0)} 熱門*")

    # ── Features Summary ────────────────────────────────────────
    if features:
        lines.append("")
        lines.append("## 💡 功能摘要")
        lines.append("")
        lines.append("| # | 功能 | 摘要 | 連結 |")
        lines.append("|---|---------|---------|------|")
        for item in features[:15]:
            num = item.get("url", "").split("/")[-1]
            title = item["title"][:55] + ("..." if len(item["title"]) > 55 else "")
            body = (item.get("body_preview") or "")
            for prefix in ["### Summary", "## Summary", "### Problem", "## Problem",
                           "### Description", "## Description", "### Summary\n"]:
                body = body.replace(prefix, "")
            body = body.replace("\n", " ").replace("  ", " ").strip()[:90]
            url = item.get("url", "")
            lines.append(f"| {num} | {title} | {body} | [連結]({url}) |")

    # ── Traditional Chinese Resources ─────────────────────────
    tw_resources = [
        ("openclaw.cocoloop.cn/zh-tw", "OpenClaw繁體社群 — 繁體中文教程、文檔、工具與指南"),
        ("www.openclaw.org.tw", "OpenClaw 台灣社群 — 台灣在地技術支援"),
    ]
    lines.append("")
    lines.append("## 🌐 繁體中文資源")
    lines.append("")
    lines.append("| 站點 | 說明 |")
    lines.append("|------|------|")
    for site, desc in tw_resources:
        lines.append(f"| [{site}](https://{site}) | {desc} |")

    return "\n".join(lines)


def main():
    print("🔍 掃描 OpenClaw 社群來源...")

    headers = gh_headers()

    # Recent GitHub Issues
    gh_issues = []
    for repo_id, repo_name in GH_REPOS:
        print(f"  → Issues ({repo_id})...")
        url = f"https://api.github.com/repos/{repo_name}/issues?state=open&per_page=15"
        raw = fetch(url, headers=headers)
        if raw:
            parsed = parse_gh_issues(raw)
            for item in parsed:
                item["repo"] = repo_id
            gh_issues.extend(parsed)
            print(f"    {len(parsed)} recent issues from {repo_name}")
        else:
            print(f"    Failed: {repo_name}")

    # Enhancement-labeled issues
    print("  → Enhancement features...")
    feat_url = "https://api.github.com/repos/openclaw/openclaw/issues?state=open&per_page=10&labels=enhancement&sort=updated"
    feat_raw = fetch(feat_url, headers=headers)
    if feat_raw:
        feat_parsed = parse_gh_issues(feat_raw, skip_date_filter=True)
        for item in feat_parsed:
            item["repo"] = "openclaw_core"
        gh_issues.extend(feat_parsed)
        print(f"    {len(feat_parsed)} enhancement issues")
    else:
        print("    Failed")

    # GitHub Discussions
    print("  → Discussions...")
    repo_check = fetch(f"https://api.github.com/repos/{GH_DISCUSSIONS_REPO}", headers=headers)
    has_discussions = False
    if repo_check:
        try:
            has_discussions = json.loads(repo_check).get("has_discussions", False)
        except Exception:
            pass
    gh_discussions_data = None
    if has_discussions:
        q = """
        {
          repository(owner: "openclaw-community", name: "openclaw-hub") {
            discussions(first: 20, orderBy: {field: CREATED_AT, direction: DESC}) {
              nodes { title url createdAt category { name }
                comments { totalCount } body }
            }
          }
        }
        """
        gh_discussions_data = gh_graphql_query(q, headers)
    gh_discussions = parse_gh_discussions(gh_discussions_data) if gh_discussions_data else []
    if not has_discussions:
        print("    Discussions not enabled on openclaw-community/openclaw-hub")
    else:
        print(f"    {len(gh_discussions)} discussions")

    # Reddit — General search
    print("  → Reddit (general)...")
    reddit_raw = fetch(REDDIT_SEARCH_URL, headers={"User-Agent": CUSTOM_USER_AGENT})
    reddit = parse_reddit(reddit_raw) if reddit_raw else []
    print(f"    {len(reddit)} posts")

    # Reddit — r/openclaw Use Cases
    print("  → Reddit (r/openclaw Use Cases)...")
    reddit_uc_raw = fetch(REDDIT_USE_CASES_URL, headers={"User-Agent": CUSTOM_USER_AGENT})
    reddit_use_cases = parse_reddit_use_cases(reddit_uc_raw) if reddit_uc_raw else []
    print(f"    {len(reddit_use_cases)} use case posts")

    # Reddit — r/openclaw Hot
    print("  → Reddit (r/openclaw Hot)...")
    reddit_hot_raw = fetch(REDDIT_HOT_URL, headers={"User-Agent": CUSTOM_USER_AGENT})
    reddit_hot = parse_reddit(reddit_hot_raw, source_type="reddit_hot") if reddit_hot_raw else []
    print(f"    {len(reddit_hot)} hot posts")

    # Deduplicate by title
    def dedup(items):
        seen = set()
        result = []
        for x in items:
            key = x["title"].lower().strip()
            if key not in seen:
                seen.add(key)
                result.append(x)
        return result

    gh_issues = dedup(gh_issues)
    reddit = dedup(reddit)
    reddit_use_cases = dedup(reddit_use_cases)
    reddit_hot = dedup(reddit_hot)

    print(f"    去重後：{len(gh_issues)} issues, {len(reddit)} reddit, {len(reddit_use_cases)} use cases, {len(reddit_hot)} hot")

    report = build_report(gh_issues, gh_discussions, reddit, reddit_use_cases, reddit_hot, has_discussions)
    OUTPUT_FILE.write_text(json.dumps(report, indent=2))
    save_state(report)

    md = format_markdown(report)
    print()
    print(md)
    return md


if __name__ == "__main__":
    main()