#!/usr/bin/env python3
"""Skill Marketplace Analyzer — MVP core engine."""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "skills.db"
DASHBOARD_DEFAULT = "/tmp/skill-analyzer-dashboard.html"

CATEGORIES = {
    "coding": ["code", "programming", "refactor", "lint", "debug", "compiler", "typescript", "python", "rust", "java"],
    "browser": ["browser", "playwright", "puppeteer", "selenium", "web scraping", "crawl"],
    "search": ["search", "retrieval", "knowledge", "rag", "index"],
    "media": ["image", "video", "audio", "tts", "speech", "dall-e", "midjourney", "music"],
    "cloud": ["cloud", "deploy", "devops", "docker", "kubernetes", "aws", "azure", "gcp", "terraform"],
    "data": ["data", "database", "sql", "analytics", "csv", "pandas", "etl"],
    "security": ["security", "audit", "pentest", "vulnerability", "firewall"],
    "productivity": ["calendar", "email", "task", "todo", "reminder", "note", "schedule"],
    "social": ["social", "twitter", "discord", "slack", "reddit", "xiaohongshu", "wechat"],
    "finance": ["finance", "trading", "stock", "crypto", "market", "invest"],
    "memory": ["memory", "context", "knowledge graph", "embedding", "vector"],
    "integration": ["api", "webhook", "integration", "connector", "oauth"],
}

QUALITY_WEIGHTS = [
    ("has_skill_md", 20),
    ("has_references", 15),
    ("has_scripts", 15),
    ("script_count_gt3", 10),
    ("has_readme", 10),
    ("long_description", 10),
    ("has_meta_json", 5),
    ("recent_update", 15),
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(db_path: Path | None = None):
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            name TEXT,
            source TEXT,
            category TEXT,
            description TEXT,
            stars INTEGER DEFAULT 0,
            downloads INTEGER DEFAULT 0,
            quality_score REAL DEFAULT 0,
            has_references BOOLEAN DEFAULT 0,
            has_scripts BOOLEAN DEFAULT 0,
            script_count INTEGER DEFAULT 0,
            readme_quality TEXT DEFAULT 'poor',
            last_updated TEXT,
            scanned_at TEXT
        )
    """)
    conn.commit()
    return conn

def upsert_skill(conn: sqlite3.Connection, skill: dict):
    conn.execute("""
        INSERT INTO skills (id, name, source, category, description, stars, downloads,
            quality_score, has_references, has_scripts, script_count, readme_quality,
            last_updated, scanned_at)
        VALUES (:id, :name, :source, :category, :description, :stars, :downloads,
            :quality_score, :has_references, :has_scripts, :script_count, :readme_quality,
            :last_updated, :scanned_at)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, source=excluded.source, category=excluded.category,
            description=excluded.description, stars=excluded.stars, downloads=excluded.downloads,
            quality_score=excluded.quality_score, has_references=excluded.has_references,
            has_scripts=excluded.has_scripts, script_count=excluded.script_count,
            readme_quality=excluded.readme_quality, last_updated=excluded.last_updated,
            scanned_at=excluded.scanned_at
    """, skill)
    conn.commit()

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(name: str, description: str) -> str:
    text = f"{name} {description}".lower()
    scores = {}
    for cat, keywords in CATEGORIES.items():
        scores[cat] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"

# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

def compute_quality(skill: dict) -> float:
    score = 0.0
    if skill.get("has_skill_md"):
        score += 20
    if skill.get("has_references"):
        score += 15
    if skill.get("has_scripts"):
        score += 15
    if skill.get("script_count", 0) > 3:
        score += 10
    if skill.get("has_readme"):
        score += 10
    if len(skill.get("description", "") or "") > 100:
        score += 10
    if skill.get("has_meta_json"):
        score += 5
    # recent update
    lu = skill.get("last_updated")
    if lu:
        try:
            dt = datetime.fromisoformat(lu.replace("Z", "+00:00"))
            if (datetime.now(dt.tzinfo) - dt).days <= 30:
                score += 15
        except Exception:
            pass
    return score

def readme_quality_label(desc: str | None) -> str:
    if not desc:
        return "poor"
    l = len(desc)
    if l > 300:
        return "good"
    if l > 100:
        return "fair"
    return "poor"

# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------

def scan_clawhub(conn: sqlite3.Connection):
    """Scan ClawHub skills via the clawhub CLI."""
    print("[scan] Scanning ClawHub...")
    try:
        result = subprocess.run(
            ["openclaw", "skills", "list", "--json"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            # Try clawhub CLI
            result = subprocess.run(
                ["clawhub", "list", "--json"],
                capture_output=True, text=True, timeout=60
            )
    except FileNotFoundError:
        print("[scan] clawhub/openclaw CLI not found, skipping ClawHub scan")
        return 0

    count = 0
    try:
        skills_data = json.loads(result.stdout)
        if not isinstance(skills_data, list):
            skills_data = skills_data.get("skills", [])
    except (json.JSONDecodeError, AttributeError):
        print("[scan] Could not parse ClawHub output")
        return 0

    now = datetime.now().isoformat()
    for s in skills_data:
        name = s.get("name", "unknown")
        desc = s.get("description", "")
        skill = {
            "id": f"clawhub:{name}",
            "name": name,
            "source": "clawhub",
            "category": classify(name, desc),
            "description": desc,
            "stars": s.get("stars", 0),
            "downloads": s.get("downloads", s.get("installs", 0)),
            "has_references": s.get("has_references", False),
            "has_scripts": s.get("has_scripts", False),
            "script_count": s.get("script_count", 0),
            "has_skill_md": True,
            "has_readme": bool(desc),
            "has_meta_json": s.get("has_meta_json", False),
            "last_updated": s.get("last_updated", now),
            "scanned_at": now,
        }
        skill["quality_score"] = compute_quality(skill)
        skill["readme_quality"] = readme_quality_label(desc)
        upsert_skill(conn, skill)
        skill["url"] = f"https://clawhub.com/skills/{name}"
        count += 1

    print(f"[scan] ClawHub: {count} skills")
    return count

def scan_github(conn: sqlite3.Connection):
    """Scan GitHub for agent skill repos via gh CLI."""
    print("[scan] Scanning GitHub...")
    try:
        result = subprocess.run(
            ["gh", "search", "repos", "SKILL.md", "--topic=skill-md",
             "--json", "name,description,stargazersCount,url,updatedAt",
             "--limit", "100"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f"[scan] gh search failed: {result.stderr[:200]}")
            return 0
    except FileNotFoundError:
        print("[scan] gh CLI not found, skipping GitHub scan")
        return 0

    count = 0
    now = datetime.now().isoformat()
    try:
        repos = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("[scan] Could not parse GitHub output")
        return 0

    for r in repos:
        name = r.get("name", "unknown")
        desc = r.get("description", "") or ""
        skill = {
            "id": f"github:{name}",
            "name": name,
            "source": "github",
            "category": classify(name, desc),
            "description": desc,
            "stars": r.get("stargazersCount", 0),
            "downloads": 0,
            "has_references": False,
            "has_scripts": False,
            "script_count": 0,
            "has_skill_md": True,
            "has_readme": bool(desc),
            "has_meta_json": False,
            "last_updated": r.get("updatedAt", now),
            "scanned_at": now,
        }
        skill["quality_score"] = compute_quality(skill)
        skill["readme_quality"] = readme_quality_label(desc)
        upsert_skill(conn, skill)
        count += 1

    print(f"[scan] GitHub: {count} skills")
    return count

# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def generate_report(conn: sqlite3.Connection, top: int = 20):
    print(f"\n{'='*60}")
    print("  SKILL MARKETPLACE ANALYSIS REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    avg_q = conn.execute("SELECT AVG(quality_score) FROM skills").fetchone()[0] or 0
    cats = conn.execute("SELECT COUNT(DISTINCT category) FROM skills").fetchone()[0]
    print(f"  Total Skills: {total}")
    print(f"  Avg Quality:  {avg_q:.1f}/100")
    print(f"  Categories:   {cats}\n")

    print(f"--- Top {top} by Stars ---")
    rows = conn.execute(
        "SELECT name, source, stars, quality_score, category FROM skills ORDER BY stars DESC LIMIT ?",
        (top,)
    ).fetchall()
    for i, r in enumerate(rows, 1):
        print(f"  {i:2}. [{r['source']:8}] ⭐{r['stars']:5}  Q:{r['quality_score']:5.1f}  {r['name']} ({r['category']})")

    print(f"\n--- Category Distribution ---")
    cats_rows = conn.execute(
        "SELECT category, COUNT(*) as cnt, AVG(quality_score) as avg_q FROM skills GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    for r in cats_rows:
        print(f"  {r['category']:15} {r['cnt']:4} skills  avg_q={r['avg_q']:.1f}")

    # Security & Compatibility statistics
    print(f"\n--- Security Overview ---")
    print(f"  (Security scanning available per-skill with scan_security())")
    print(f"  PII detection integrated — scan_pii() checks for emails, phone numbers,")
    print(f"  API keys, IP addresses, ID cards, bank cards, and URL secrets.")
    print(f"  Use --dashboard for per-skill security & PII ratings")

    print(f"\n--- Platform Compatibility Overview ---")
    print(f"  (Compatibility checking available per-skill with check_compatibility())")
    print(f"  Use --dashboard for per-skill platform indicators")

    # Source distribution
    src_rows = conn.execute(
        "SELECT source, COUNT(*) as cnt FROM skills GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    print(f"\n--- Source Distribution ---")
    for r in src_rows:
        print(f"  {r['source']:15} {r['cnt']:4} skills")

    print()

def find_gaps(conn: sqlite3.Connection):
    print(f"\n{'='*60}")
    print("  MARKET GAP ANALYSIS")
    print(f"{'='*60}\n")

    cats_rows = conn.execute(
        "SELECT category, COUNT(*) as cnt, AVG(quality_score) as avg_q FROM skills GROUP BY category ORDER BY cnt ASC"
    ).fetchall()

    all_categories = set(CATEGORIES.keys())
    present = {r["category"] for r in cats_rows}
    missing = all_categories - present

    if missing:
        print("  🔴 Missing categories (zero skills):")
        for c in sorted(missing):
            print(f"     - {c}")

    print("\n  🟡 Underserved categories (few skills or low quality):")
    for r in cats_rows:
        if r["cnt"] < 5 or r["avg_q"] < 40:
            print(f"     - {r['category']}: {r['cnt']} skills, avg quality {r['avg_q']:.1f}")

    total = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    low_q = conn.execute("SELECT COUNT(*) FROM skills WHERE quality_score < 30").fetchone()[0]
    if total > 0:
        print(f"\n  📊 {low_q}/{total} skills ({100*low_q/total:.0f}%) have quality < 30 — room for better alternatives")
    print()

# ---------------------------------------------------------------------------
# Mock data (for testing)
# ---------------------------------------------------------------------------

MOCK_SKILLS = [
    {"name": "github-pr-review", "source": "clawhub", "desc": "Automated GitHub pull request review with AI-powered code analysis, security scanning, and style checking. Supports multiple languages and custom rules.", "stars": 1200, "downloads": 8500, "has_references": True, "has_scripts": True, "script_count": 5, "has_meta_json": True, "days_ago": 3},
    {"name": "browser-automation", "source": "clawhub", "desc": "Full browser automation using Playwright. Navigate, click, fill forms, take screenshots, and extract data from any website.", "stars": 980, "downloads": 6200, "has_references": True, "has_scripts": True, "script_count": 4, "has_meta_json": True, "days_ago": 7},
    {"name": "tavily-search", "source": "clawhub", "desc": "Web search powered by Tavily API with depth control and domain filtering.", "stars": 850, "downloads": 12000, "has_references": True, "has_scripts": False, "script_count": 0, "has_meta_json": True, "days_ago": 2},
    {"name": "memory-manager", "source": "clawhub", "desc": "Persistent memory management for AI agents. Store, retrieve, and organize contextual information across sessions using vector embeddings.", "stars": 720, "downloads": 4100, "has_references": True, "has_scripts": True, "script_count": 3, "has_meta_json": False, "days_ago": 15},
    {"name": "docker-deploy", "source": "github", "desc": "One-click Docker container deployment and management.", "stars": 650, "downloads": 0, "has_references": False, "has_scripts": True, "script_count": 6, "has_meta_json": False, "days_ago": 10},
    {"name": "dalle-generator", "source": "clawhub", "desc": "Generate images using DALL-E 3 with prompt optimization and style presets.", "stars": 580, "downloads": 3800, "has_references": True, "has_scripts": False, "script_count": 0, "has_meta_json": True, "days_ago": 5},
    {"name": "sql-analyzer", "source": "github", "desc": "Analyze and optimize SQL queries with explain plans.", "stars": 420, "downloads": 0, "has_references": False, "has_scripts": True, "script_count": 2, "has_meta_json": False, "days_ago": 45},
    {"name": "slack-bot", "source": "clawhub", "desc": "Slack integration for AI agents.", "stars": 380, "downloads": 2100, "has_references": True, "has_scripts": True, "script_count": 4, "has_meta_json": True, "days_ago": 20},
    {"name": "tts-voice", "source": "clawhub", "desc": "Text-to-speech with ElevenLabs, supporting multiple voices and languages. High quality audio output.", "stars": 350, "downloads": 1900, "has_references": True, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 8},
    {"name": "redis-cache", "source": "github", "desc": "Redis caching layer for agents.", "stars": 310, "downloads": 0, "has_references": False, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 60},
    {"name": "security-audit", "source": "clawhub", "desc": "Automated security scanning for codebases including dependency checks, secret detection, and OWASP compliance verification.", "stars": 290, "downloads": 1500, "has_references": True, "has_scripts": True, "script_count": 7, "has_meta_json": True, "days_ago": 4},
    {"name": "calendar-sync", "source": "clawhub", "desc": "Sync and manage Google Calendar events.", "stars": 260, "downloads": 1800, "has_references": False, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 35},
    {"name": "csv-processor", "source": "github", "desc": "Process and analyze CSV files.", "stars": 240, "downloads": 0, "has_references": False, "has_scripts": True, "script_count": 1, "has_meta_json": False, "days_ago": 90},
    {"name": "twitter-poster", "source": "clawhub", "desc": "Post tweets and threads with AI-optimized content. Supports scheduling and analytics.", "stars": 220, "downloads": 900, "has_references": True, "has_scripts": True, "script_count": 2, "has_meta_json": False, "days_ago": 12},
    {"name": "k8s-manager", "source": "github", "desc": "Kubernetes cluster management and monitoring.", "stars": 190, "downloads": 0, "has_references": False, "has_scripts": True, "script_count": 3, "has_meta_json": False, "days_ago": 25},
    {"name": "notion-sync", "source": "clawhub", "desc": "Bidirectional sync between Notion and local markdown files.", "stars": 170, "downloads": 1100, "has_references": True, "has_scripts": False, "script_count": 0, "has_meta_json": True, "days_ago": 18},
    {"name": "stock-tracker", "source": "github", "desc": "Real-time stock price tracking with alerts.", "stars": 150, "downloads": 0, "has_references": False, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 40},
    {"name": "pdf-reader", "source": "clawhub", "desc": "Extract text and tables from PDF files.", "stars": 130, "downloads": 2200, "has_references": False, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 50},
    {"name": "whisper-transcribe", "source": "github", "desc": "Audio transcription using OpenAI Whisper with speaker diarization and timestamp support.", "stars": 110, "downloads": 0, "has_references": True, "has_scripts": True, "script_count": 2, "has_meta_json": False, "days_ago": 6},
    {"name": "quick-lint", "source": "github", "desc": "Fast linting.", "stars": 45, "downloads": 0, "has_references": False, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 120},
    {"name": "email-helper", "source": "clawhub", "desc": "Draft, send, and manage emails across Gmail and Outlook with AI assistance for tone and content.", "stars": 88, "downloads": 650, "has_references": True, "has_scripts": True, "script_count": 3, "has_meta_json": True, "days_ago": 9},
    {"name": "vector-search", "source": "github", "desc": "Semantic vector search using FAISS or Pinecone.", "stars": 95, "downloads": 0, "has_references": False, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 22},
    {"name": "terraform-plan", "source": "github", "desc": "Run Terraform plan and apply with safety checks.", "stars": 75, "downloads": 0, "has_references": False, "has_scripts": True, "script_count": 2, "has_meta_json": False, "days_ago": 30},
    {"name": "discord-bot", "source": "clawhub", "desc": "Discord bot framework for AI agent integration. Supports slash commands, reactions, threads, and voice channels.", "stars": 440, "downloads": 3100, "has_references": True, "has_scripts": True, "script_count": 5, "has_meta_json": True, "days_ago": 1},
    {"name": "xiaohongshu-poster", "source": "clawhub", "desc": "Auto-post to Xiaohongshu (小红书) with image generation and hashtag optimization.", "stars": 320, "downloads": 1400, "has_references": True, "has_scripts": True, "script_count": 3, "has_meta_json": True, "days_ago": 5},
    {"name": "feishu-doc-sync", "source": "clawhub", "desc": "飞书文档同步工具，支持双向同步 Markdown 和飞书文档。Requires feishu API_KEY.", "stars": 280, "downloads": 950, "has_references": True, "has_scripts": True, "script_count": 2, "has_meta_json": True, "days_ago": 3},
    {"name": "wecom-bot", "source": "github", "desc": "企业微信机器人集成，支持消息推送和审批流程。Install with pip install wecom-sdk.", "stars": 210, "downloads": 0, "has_references": False, "has_scripts": True, "script_count": 3, "has_meta_json": False, "days_ago": 8},
    {"name": "zh-summarizer", "source": "clawhub", "desc": "中文文本摘要生成，基于 ANTHROPIC_API_KEY 驱动的大模型。", "stars": 175, "downloads": 600, "has_references": True, "has_scripts": False, "script_count": 0, "has_meta_json": False, "days_ago": 12},
    {"name": "douyin-analytics", "source": "github", "desc": "抖音数据分析工具，追踪视频表现和粉丝增长趋势。", "stars": 410, "downloads": 0, "has_references": False, "has_scripts": True, "script_count": 4, "has_meta_json": False, "days_ago": 2},
    {"name": "a-stock-tracker", "source": "github", "desc": "A股实时行情追踪与智能选股，支持同花顺数据源。OPENAI_API_KEY required.", "stars": 520, "downloads": 0, "has_references": True, "has_scripts": True, "script_count": 5, "has_meta_json": True, "days_ago": 1},
]


def load_mock_data(conn: sqlite3.Connection):
    """Load mock skill data for testing."""
    now = datetime.now()
    for m in MOCK_SKILLS:
        updated = (now - timedelta(days=m["days_ago"])).isoformat()
        skill = {
            "id": f"{m['source']}:{m['name']}",
            "name": m["name"],
            "source": m["source"],
            "category": classify(m["name"], m["desc"]),
            "description": m["desc"],
            "stars": m["stars"],
            "downloads": m["downloads"],
            "has_references": m["has_references"],
            "has_scripts": m["has_scripts"],
            "script_count": m["script_count"],
            "has_skill_md": True,
            "has_readme": True,
            "has_meta_json": m["has_meta_json"],
            "last_updated": updated,
            "scanned_at": now.isoformat(),
        }
        skill["quality_score"] = compute_quality(skill)
        skill["readme_quality"] = readme_quality_label(m["desc"])
        upsert_skill(conn, skill)
    print(f"[mock] Loaded {len(MOCK_SKILLS)} mock skills")

# ---------------------------------------------------------------------------
# Chinese Ecosystem Analysis
# ---------------------------------------------------------------------------

def _has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    if not text:
        return False
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def analyze_chinese_ecosystem(db_path: Path | None = None) -> dict:
    """Analyze Chinese-language skills in the marketplace."""
    conn = init_db(db_path)
    rows = conn.execute("SELECT id, name, category, description, stars FROM skills").fetchall()

    chinese_skills = []
    all_by_cat: dict[str, list] = {}
    chinese_by_cat: dict[str, list] = {}

    chinese_tags = {"zh", "chinese", "中文"}

    for r in rows:
        cat = r["category"]
        all_by_cat.setdefault(cat, []).append(r)

        name = r["name"] or ""
        desc = r["description"] or ""
        is_chinese = (
            _has_chinese(name) or
            _has_chinese(desc) or
            any(tag in name.lower() for tag in chinese_tags) or
            any(tag in desc.lower() for tag in chinese_tags)
        )
        if is_chinese:
            chinese_skills.append(r)
            chinese_by_cat.setdefault(cat, []).append(r)

    total = len(rows)
    total_chinese = len(chinese_skills)
    percentage = (total_chinese / total * 100) if total > 0 else 0

    by_category = {cat: len(skills) for cat, skills in chinese_by_cat.items()}

    # Gaps: categories with English skills but no Chinese
    gaps = []
    for cat in sorted(all_by_cat.keys()):
        if cat not in chinese_by_cat:
            gaps.append({"category": cat, "english_count": len(all_by_cat[cat])})

    top_chinese = sorted(chinese_skills, key=lambda r: r["stars"], reverse=True)[:10]
    top_chinese = [{"name": r["name"], "category": r["category"], "stars": r["stars"]} for r in top_chinese]

    return {
        "total_chinese": total_chinese,
        "percentage": round(percentage, 1),
        "by_category": by_category,
        "gaps": gaps,
        "top_chinese": top_chinese,
    }


# ---------------------------------------------------------------------------
# Dependency Graph
# ---------------------------------------------------------------------------

TOOL_PATTERNS = [
    re.compile(r'(?:requires?|bins?|install)\s*[:\-]?\s*[`"\']?(\w[\w-]+)', re.IGNORECASE),
    re.compile(r'(?:pip|npm|brew|apt|cargo)\s+install\s+(\S+)', re.IGNORECASE),
]

API_KEY_PATTERNS = [
    re.compile(r'(\w*(?:API_KEY|SECRET|TOKEN)\w*)', re.IGNORECASE),
    re.compile(r'(OPENAI\w*)', re.IGNORECASE),
    re.compile(r'(ANTHROPIC\w*)', re.IGNORECASE),
    re.compile(r'(TAVILY\w*)', re.IGNORECASE),
    re.compile(r'(GOOGLE\w*KEY\w*)', re.IGNORECASE),
]


def build_dependency_graph(db_path: Path | None = None) -> dict:
    """Analyze skill dependencies from SKILL.md content and DB metadata."""
    conn = init_db(db_path)
    rows = conn.execute("SELECT id, name, category, description FROM skills").fetchall()

    all_names = {r["name"] for r in rows}
    nodes = []
    edges = []
    tool_deps: dict[str, list[str]] = {}
    api_deps: dict[str, list[str]] = {}

    for r in rows:
        node_id = r["id"]
        name = r["name"]
        nodes.append({"id": node_id, "name": name, "category": r["category"]})

        desc = (r["description"] or "").lower()
        full_text = f"{name} {r['description'] or ''}"

        # Tool dependencies
        tools_found = set()
        for pat in TOOL_PATTERNS:
            for m in pat.finditer(full_text):
                tool = m.group(1).lower().strip()
                if tool not in {"the", "a", "an", "is", "and", "or", "for", "with", name.lower()}:
                    tools_found.add(tool)
        if tools_found:
            tool_deps[name] = sorted(tools_found)
            for t in tools_found:
                edges.append({"source": node_id, "target": f"tool:{t}", "type": "tool_dep"})

        # API key dependencies
        apis_found = set()
        for pat in API_KEY_PATTERNS:
            for m in pat.finditer(full_text):
                apis_found.add(m.group(1).upper())
        if apis_found:
            api_deps[name] = sorted(apis_found)
            for a in apis_found:
                edges.append({"source": node_id, "target": f"api:{a}", "type": "api_dep"})

        # Cross-skill references
        for other_name in all_names:
            if other_name != name and other_name.lower() in desc:
                edges.append({"source": node_id, "target": f"{r['category']}:{other_name}", "type": "skill_ref"})

    return {
        "nodes": nodes,
        "edges": edges,
        "tool_deps": tool_deps,
        "api_deps": api_deps,
    }


# ---------------------------------------------------------------------------
# Trend Prediction
# ---------------------------------------------------------------------------

def predict_trends(db_path: Path | None = None) -> dict:
    """Predict trending skills based on star growth rates."""
    conn = init_db(db_path)
    rows = conn.execute(
        "SELECT name, category, stars, last_updated, scanned_at FROM skills WHERE stars > 0"
    ).fetchall()

    skill_trends = []
    cat_growth: dict[str, list[float]] = {}

    now = datetime.now()

    for r in rows:
        name = r["name"]
        stars = r["stars"]
        category = r["category"]

        # Estimate growth rate: stars / repo_age_in_days
        age_days = 365  # default 1 year
        lu = r["last_updated"]
        if lu:
            try:
                dt = datetime.fromisoformat(lu.replace("Z", "+00:00")).replace(tzinfo=None)
                # Use recency as a proxy: recently updated repos are "younger" in activity
                days_since_update = max(1, (now - dt).days)
                # More recent updates → higher implied growth
                age_days = max(30, days_since_update * 10)  # scale factor
            except Exception:
                pass

        growth_rate = round(stars / age_days, 2)
        skill_trends.append({
            "name": name,
            "category": category,
            "stars": stars,
            "growth_rate": growth_rate,
        })
        cat_growth.setdefault(category, []).append(growth_rate)

    # Top 10 trending
    trending = sorted(skill_trends, key=lambda x: x["growth_rate"], reverse=True)[:10]

    # Category growth
    growing_categories = []
    for cat, rates in cat_growth.items():
        avg = sum(rates) / len(rates)
        growing_categories.append({"name": cat, "growth": round(avg, 2)})
    growing_categories.sort(key=lambda x: x["growth"], reverse=True)

    return {
        "trending_skills": trending,
        "growing_categories": growing_categories,
    }


# ---------------------------------------------------------------------------
# Security Scanner
# ---------------------------------------------------------------------------

SECURITY_PATTERNS = [
    # (regex, risk_type, severity)
    (re.compile(r'rm\s+-rf\b'), "filesystem_danger", "high"),
    (re.compile(r'shutil\.rmtree\b'), "filesystem_danger", "high"),
    (re.compile(r'os\.remove\b'), "filesystem_danger", "medium"),
    (re.compile(r'\bexec\s*\('), "code_injection", "high"),
    (re.compile(r'\beval\s*\('), "code_injection", "high"),
    (re.compile(r'\bcompile\s*\('), "code_injection", "medium"),
    (re.compile(r'subprocess\.call\([^)]*shell\s*=\s*True'), "shell_injection", "high"),
    (re.compile(r'subprocess\.run\([^)]*shell\s*=\s*True'), "shell_injection", "high"),
    (re.compile(r'''(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*["'][^"']{8,}["']''', re.IGNORECASE), "credential_leak", "high"),
    (re.compile(r'''token\s*=\s*["']sk-[^"']+["']''', re.IGNORECASE), "credential_leak", "high"),
    (re.compile(r'requests\.(?:get|post|put|delete|patch)\s*\([^)]*(?:https?://(?!localhost|127\.0\.0\.1))'), "network_access", "low"),
    (re.compile(r'open\s*\([^)]*["\']w["\']'), "file_write", "low"),
]

# ---------------------------------------------------------------------------
# PII Scanner
# ---------------------------------------------------------------------------

PII_PATTERNS = [
    # (regex, pii_type)
    (re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}'), "email"),
    (re.compile(r'\b1[3-9]\d{9}\b'), "phone"),
    (re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'), "ip_address"),
    (re.compile(r'\b(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|cfut_[a-zA-Z0-9]+|tvly-[a-zA-Z0-9]+)\b'), "api_key"),
    (re.compile(r'\b\d{17}[\dXx]\b'), "id_card"),
    (re.compile(r'\b\d{16,19}\b'), "bank_card"),
    (re.compile(r'[?&](?:token|secret|api_key|access_token|password)=[^&\s]{6,}', re.IGNORECASE), "url_secret"),
]

PII_SCAN_EXTENSIONS = {".py", ".js", ".md", ".yaml", ".yml"}


def _mask_value(val: str) -> str:
    """Show only first 3 and last 3 chars."""
    if len(val) <= 6:
        return "***"
    return val[:3] + "***" + val[-3:]


def scan_pii(skill_dir: str) -> dict:
    """Scan a skill directory for PII (personally identifiable information)."""
    findings = []
    skill_path = Path(skill_dir)

    if not skill_path.is_dir():
        return {"pii_count": 0, "findings": [], "risk_level": "none"}

    for fpath in skill_path.rglob("*"):
        if fpath.suffix not in PII_SCAN_EXTENSIONS or not fpath.is_file():
            continue
        try:
            lines = fpath.read_text(errors="ignore").splitlines()
        except Exception:
            continue
        rel = str(fpath.relative_to(skill_path))
        for lineno, line in enumerate(lines, 1):
            for pattern, pii_type in PII_PATTERNS:
                for m in pattern.finditer(line):
                    value = m.group(0)
                    # Exclude localhost / loopback IPs
                    if pii_type == "ip_address" and value in ("127.0.0.1", "0.0.0.0"):
                        continue
                    findings.append({
                        "type": pii_type,
                        "value_masked": _mask_value(value),
                        "file": rel,
                        "line": lineno,
                    })

    pii_count = len(findings)
    if pii_count == 0:
        risk_level = "none"
    elif pii_count <= 3:
        risk_level = "low"
    else:
        risk_level = "high"

    return {"pii_count": pii_count, "findings": findings, "risk_level": risk_level}


# ---------------------------------------------------------------------------
# Security Scanner
# ---------------------------------------------------------------------------

def scan_security(skill_dir: str) -> dict:
    """Scan a skill directory for security risks."""
    risks = []
    scan_extensions = {".py", ".sh", ".js", ".mjs"}
    skill_path = Path(skill_dir)

    if not skill_path.is_dir():
        return {"score": 100, "risks": [], "rating": "safe"}

    for fpath in skill_path.rglob("*"):
        if fpath.suffix not in scan_extensions or not fpath.is_file():
            continue
        try:
            lines = fpath.read_text(errors="ignore").splitlines()
        except Exception:
            continue
        rel = str(fpath.relative_to(skill_path))
        for lineno, line in enumerate(lines, 1):
            for pattern, risk_type, severity in SECURITY_PATTERNS:
                if pattern.search(line):
                    risks.append({
                        "type": risk_type,
                        "severity": severity,
                        "file": rel,
                        "line": lineno,
                        "snippet": line.strip()[:120],
                    })

    # Score: start at 100, deduct per risk
    score = 100
    for r in risks:
        if r["severity"] == "high":
            score -= 25
        elif r["severity"] == "medium":
            score -= 10
        else:
            score -= 5
    score = max(0, score)

    # Rating
    has_high = any(r["severity"] == "high" for r in risks)
    if has_high:
        rating = "dangerous"
    elif len(risks) == 0:
        rating = "safe"
    elif len([r for r in risks if r["severity"] == "low"]) <= 3 and not has_high:
        rating = "caution"
    else:
        rating = "caution"

    # PII integration
    pii_result = scan_pii(skill_dir)

    return {"score": score, "risks": risks, "rating": rating, "pii": pii_result}


# ---------------------------------------------------------------------------
# Compatibility Checker
# ---------------------------------------------------------------------------

PLATFORM_SIGNATURES = {
    "openclaw": [
        re.compile(r'\bmemory_search\b'),
        re.compile(r'\bsessions_spawn\b'),
        re.compile(r'\bmessage\s+tool\b'),
        re.compile(r'\bsessions_yield\b'),
        re.compile(r'\bcanvas\b.*\bsnapshot\b'),
        re.compile(r'\bfeishu_'),
        re.compile(r'\btavily_search\b'),
    ],
    "claude_code": [
        re.compile(r'\bexecute_command\b'),
        re.compile(r'\bmanage_process\b'),
        re.compile(r'\bBash\b.*\btool\b'),
    ],
    "cursor": [
        re.compile(r'\bcodebase_search\b'),
        re.compile(r'\blist_dir\b'),
        re.compile(r'\bfile_search\b'),
    ],
    "codex": [
        re.compile(r'\bcodex\b', re.IGNORECASE),
    ],
}

def check_compatibility(skill_dir: str) -> dict:
    """Check which platforms a skill is compatible with."""
    skill_path = Path(skill_dir)
    skill_md = skill_path / "SKILL.md"
    issues = []
    platforms_detected = set()
    format_valid = True

    if not skill_md.is_file():
        return {"platforms": ["generic"], "format_valid": False, "issues": ["No SKILL.md found"]}

    try:
        content = skill_md.read_text(errors="ignore")
    except Exception:
        return {"platforms": ["generic"], "format_valid": False, "issues": ["Cannot read SKILL.md"]}

    # YAML frontmatter check
    if content.startswith("---"):
        end = content.find("---", 3)
        if end == -1:
            format_valid = False
            issues.append("YAML frontmatter not properly closed")
    else:
        # No frontmatter is okay but noted
        pass

    # Detect platform-specific features
    for platform, patterns in PLATFORM_SIGNATURES.items():
        for pat in patterns:
            if pat.search(content):
                platforms_detected.add(platform)
                break

    if not platforms_detected:
        platforms_detected.add("generic")

    return {
        "platforms": sorted(platforms_detected),
        "format_valid": format_valid,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Anthropic Skills Scanner
# ---------------------------------------------------------------------------

def scan_anthropic(conn: sqlite3.Connection):
    """Scan GitHub anthropics/skills repository."""
    print("[scan] Scanning Anthropic skills...")
    try:
        result = subprocess.run(
            ["gh", "api", "repos/anthropics/skills/git/trees/main?recursive=1"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"[scan] gh api failed: {result.stderr[:200]}")
            return 0
    except FileNotFoundError:
        print("[scan] gh CLI not found, skipping Anthropic scan")
        return 0

    count = 0
    now = datetime.now().isoformat()
    try:
        tree = json.loads(result.stdout)
        items = tree.get("tree", [])
    except (json.JSONDecodeError, AttributeError):
        print("[scan] Could not parse Anthropic tree")
        return 0

    # Find directories that contain SKILL.md
    skill_dirs = set()
    for item in items:
        path = item.get("path", "")
        if path.endswith("/SKILL.md") or path == "SKILL.md":
            parent = str(Path(path).parent)
            if parent == ".":
                parent = Path(path).stem
            skill_dirs.add(parent)

    for sd in skill_dirs:
        name = Path(sd).name
        desc = f"Anthropic official skill: {name}"
        skill = {
            "id": f"anthropic:{name}",
            "name": name,
            "source": "anthropic",
            "category": classify(name, desc),
            "description": desc,
            "stars": 0,
            "downloads": 0,
            "has_references": False,
            "has_scripts": False,
            "script_count": 0,
            "has_skill_md": True,
            "has_readme": True,
            "has_meta_json": False,
            "last_updated": now,
            "scanned_at": now,
        }
        skill["quality_score"] = compute_quality(skill)
        skill["readme_quality"] = readme_quality_label(desc)
        upsert_skill(conn, skill)
        count += 1

    print(f"[scan] Anthropic: {count} skills")
    return count


# ---------------------------------------------------------------------------
# Skill Recommendations
# ---------------------------------------------------------------------------

def recommend_skills(installed: list[str], db_path: Path | None = None) -> list[dict]:
    """Recommend skills based on what's already installed."""
    conn = init_db(db_path)
    rows = conn.execute("SELECT name, category, quality_score, stars FROM skills").fetchall()

    # Build category map and co-occurrence from dependency graph
    installed_set = {n.lower() for n in installed}
    installed_cats: dict[str, int] = {}
    for r in rows:
        if r["name"].lower() in installed_set:
            cat = r["category"]
            installed_cats[cat] = installed_cats.get(cat, 0) + 1

    # Find candidates: not installed, prefer same categories & high quality
    candidates = []
    for r in rows:
        if r["name"].lower() in installed_set:
            continue
        cat = r["category"]
        quality = r["quality_score"]
        stars = r["stars"]
        # Score: category affinity + quality + star bonus
        cat_affinity = installed_cats.get(cat, 0) * 15
        score = cat_affinity + quality + min(stars / 100, 20)
        reason = f"Same category as your installed skills" if cat_affinity > 0 else "High quality skill you might like"
        if cat_affinity == 0 and quality >= 60:
            reason = "Top-rated skill in a new category"
        candidates.append({
            "name": r["name"],
            "reason": reason,
            "quality_score": round(quality, 1),
            "category": cat,
            "_score": score,
        })

    candidates.sort(key=lambda x: x["_score"], reverse=True)
    for c in candidates:
        del c["_score"]
    return candidates[:5]


# ---------------------------------------------------------------------------
# Skill Comparison
# ---------------------------------------------------------------------------

def compare_skills(skill_a: str, skill_b: str, db_path: Path | None = None) -> dict:
    """Compare two skills side-by-side."""
    conn = init_db(db_path)

    def _get(name: str) -> dict | None:
        row = conn.execute(
            "SELECT name, category, quality_score, stars, description, has_references, has_scripts, script_count FROM skills WHERE name = ?",
            (name,)
        ).fetchone()
        if not row:
            return None
        # Derive security rating estimate from description
        desc = row["description"] or ""
        sec = "safe"
        if any(w in desc.lower() for w in ["exec", "shell", "sudo"]):
            sec = "caution"
        platforms = ["generic"]
        if any(w in desc.lower() for w in ["openclaw", "feishu", "tavily"]):
            platforms = ["openclaw"]
        return {
            "name": row["name"],
            "category": row["category"],
            "quality_score": round(row["quality_score"], 1),
            "stars": row["stars"],
            "security_rating": sec,
            "platforms": platforms,
            "has_references": bool(row["has_references"]),
            "has_scripts": bool(row["has_scripts"]),
            "script_count": row["script_count"],
            "description": desc[:200],
        }

    a_data = _get(skill_a)
    b_data = _get(skill_b)

    if not a_data or not b_data:
        missing = skill_a if not a_data else skill_b
        return {"error": f"Skill '{missing}' not found in database"}

    # Determine winner
    reasons = []
    a_score, b_score = 0, 0
    if a_data["quality_score"] > b_data["quality_score"]:
        a_score += 2; reasons.append(f"{skill_a} has higher quality score")
    elif b_data["quality_score"] > a_data["quality_score"]:
        b_score += 2; reasons.append(f"{skill_b} has higher quality score")
    if a_data["stars"] > b_data["stars"]:
        a_score += 1; reasons.append(f"{skill_a} has more stars")
    elif b_data["stars"] > a_data["stars"]:
        b_score += 1; reasons.append(f"{skill_b} has more stars")
    if a_data["has_scripts"] and not b_data["has_scripts"]:
        a_score += 1; reasons.append(f"{skill_a} includes automation scripts")
    elif b_data["has_scripts"] and not a_data["has_scripts"]:
        b_score += 1; reasons.append(f"{skill_b} includes automation scripts")

    winner = skill_a if a_score > b_score else skill_b if b_score > a_score else "tie"

    return {
        "skill_a": a_data,
        "skill_b": b_data,
        "winner": winner,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Contributor Analysis
# ---------------------------------------------------------------------------

def analyze_contributors(db_path: Path | None = None) -> dict:
    """Analyze top contributors/organizations from skill data."""
    conn = init_db(db_path)
    rows = conn.execute("SELECT name, source, stars, quality_score FROM skills").fetchall()

    contributors: dict[str, dict] = {}
    for r in rows:
        name = r["name"]
        source = r["source"]
        # Infer contributor from source + name patterns
        if source == "anthropic":
            contrib = "anthropics"
        elif source == "clawhub":
            # Group clawhub skills by prefix pattern
            parts = name.split("-")
            contrib = f"clawhub/{parts[0]}" if len(parts) > 1 else "clawhub/community"
        elif source == "github":
            parts = name.split("-")
            contrib = f"github/{parts[0]}" if len(parts) > 1 else "github/community"
        else:
            contrib = source

        if contrib not in contributors:
            contributors[contrib] = {"name": contrib, "skill_count": 0, "total_quality": 0.0, "total_stars": 0}
        contributors[contrib]["skill_count"] += 1
        contributors[contrib]["total_quality"] += r["quality_score"]
        contributors[contrib]["total_stars"] += r["stars"]

    # Compute avg quality and weighted score
    result = []
    for c in contributors.values():
        avg_q = round(c["total_quality"] / c["skill_count"], 1) if c["skill_count"] > 0 else 0
        # Weighted rank: quality matters more than count
        weighted = avg_q * c["skill_count"] + c["total_stars"] * 0.01
        result.append({
            "name": c["name"],
            "skill_count": c["skill_count"],
            "avg_quality": avg_q,
            "total_stars": c["total_stars"],
            "_weighted": weighted,
        })

    result.sort(key=lambda x: x["_weighted"], reverse=True)
    for r in result:
        del r["_weighted"]

    return {"top_contributors": result[:15]}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Skill Marketplace Analyzer")
    parser.add_argument("--scan", choices=["clawhub", "github", "anthropic", "all"], help="Scan data source")
    parser.add_argument("--report", action="store_true", help="Generate text report")
    parser.add_argument("--gaps", action="store_true", help="Find market gaps")
    parser.add_argument("--dashboard", nargs="?", const=DASHBOARD_DEFAULT, help="Generate HTML dashboard")
    parser.add_argument("--mock", action="store_true", help="Load mock data for testing")
    parser.add_argument("--chinese", action="store_true", help="Analyze Chinese skill ecosystem")
    parser.add_argument("--dependencies", action="store_true", help="Build dependency graph JSON")
    parser.add_argument("--trends", action="store_true", help="Predict trending skills")
    parser.add_argument("--recommend", type=str, metavar="SKILLS", help="Recommend skills based on installed list (comma-separated)")
    parser.add_argument("--compare", nargs=2, metavar=("SKILL_A", "SKILL_B"), help="Compare two skills side-by-side")
    parser.add_argument("--contributors", action="store_true", help="Analyze top contributors")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="Database path")
    parser.add_argument("--top", type=int, default=20, help="Top N for report")
    args = parser.parse_args()

    conn = init_db(Path(args.db))

    if args.mock:
        load_mock_data(conn)

    if args.scan:
        if args.scan in ("clawhub", "all"):
            scan_clawhub(conn)
        if args.scan in ("github", "all"):
            scan_github(conn)
        if args.scan in ("anthropic", "all"):
            scan_anthropic(conn)

    if args.report:
        generate_report(conn, top=args.top)
        # Append chinese ecosystem + trends sections to report
        cn = analyze_chinese_ecosystem(Path(args.db))
        print(f"\n{'='*60}")
        print("  CHINESE SKILL ECOSYSTEM")
        print(f"{'='*60}\n")
        print(f"  Chinese Skills: {cn['total_chinese']} ({cn['percentage']}% of total)")
        if cn['by_category']:
            print(f"\n  By Category:")
            for cat, cnt in sorted(cn['by_category'].items(), key=lambda x: -x[1]):
                print(f"    {cat:15} {cnt:3} skills")
        if cn['gaps']:
            print(f"\n  🔴 Gaps (categories without Chinese skills):")
            for g in cn['gaps']:
                print(f"     - {g['category']} ({g['english_count']} English-only)")
        if cn['top_chinese']:
            print(f"\n  Top Chinese Skills:")
            for s in cn['top_chinese']:
                print(f"    ⭐{s['stars']:5}  {s['name']} ({s['category']})")

        tr = predict_trends(Path(args.db))
        print(f"\n{'='*60}")
        print("  TREND PREDICTIONS")
        print(f"{'='*60}\n")
        print(f"  🚀 Top 10 Fastest Growing Skills:")
        for i, s in enumerate(tr['trending_skills'], 1):
            print(f"    {i:2}. {s['name']:25} ⭐{s['stars']:5}  growth={s['growth_rate']:.2f}/day")
        print(f"\n  📈 Growing Categories:")
        for c in tr['growing_categories']:
            print(f"    {c['name']:15} avg_growth={c['growth']:.2f}/day")
        print()

    if args.gaps:
        find_gaps(conn)

    if args.dashboard is not None:
        from dashboard_generator import generate_dashboard
        cn_data = analyze_chinese_ecosystem(Path(args.db))
        tr_data = predict_trends(Path(args.db))
        dep_data = build_dependency_graph(Path(args.db))
        contrib_data = analyze_contributors(Path(args.db))
        rec_data = None
        if args.recommend:
            installed = [s.strip() for s in args.recommend.split(",")]
            rec_data = recommend_skills(installed, Path(args.db))
        generate_dashboard(conn, args.dashboard, chinese_data=cn_data, trends_data=tr_data, dep_data=dep_data, contrib_data=contrib_data, rec_data=rec_data)

    if args.chinese:
        cn = analyze_chinese_ecosystem(Path(args.db))
        print(json.dumps(cn, indent=2, ensure_ascii=False))

    if args.dependencies:
        dep = build_dependency_graph(Path(args.db))
        print(json.dumps(dep, indent=2, ensure_ascii=False))

    if args.trends:
        tr = predict_trends(Path(args.db))
        print(json.dumps(tr, indent=2, ensure_ascii=False))

    if args.recommend:
        installed = [s.strip() for s in args.recommend.split(",")]
        recs = recommend_skills(installed, Path(args.db))
        print(json.dumps(recs, indent=2, ensure_ascii=False))

    if args.compare:
        result = compare_skills(args.compare[0], args.compare[1], Path(args.db))
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.contributors:
        result = analyze_contributors(Path(args.db))
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if not any([args.scan, args.report, args.gaps, args.dashboard is not None, args.mock,
                args.chinese, args.dependencies, args.trends, args.recommend, args.compare, args.contributors]):
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    main()
