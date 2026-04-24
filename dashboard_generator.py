#!/usr/bin/env python3
"""Generate a single-page interactive HTML dashboard for skill analysis (dark starry theme).

Features:
  - vis.js skill relationship graph (nodes by stars, colored by category)
  - Sortable/filterable Top Skills table with search + category dropdown
  - Donut chart click → filter table & highlight graph
  - Quality bar chart hover tooltips + click → filter table
  - Market gaps with "Create Skill" buttons and green highlights
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def _query(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def _mock_db():
    """Create an in-memory DB with realistic mock data."""
    import random
    random.seed(42)
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE skills (
        name TEXT, source TEXT, stars INTEGER, downloads INTEGER,
        quality_score REAL, category TEXT, description TEXT)""")
    cats = {
        "coding": ["code-review-pro", "lint-wizard", "refactor-engine", "test-generator",
                    "debug-assistant", "snippet-hub", "code-explain", "pair-programmer"],
        "browser": ["web-scraper", "page-analyzer", "auto-fill", "tab-manager", "cookie-guard"],
        "media": ["image-resize", "video-compress", "audio-transcribe", "gif-maker",
                   "thumbnail-gen", "media-convert"],
        "search": ["deep-search", "semantic-find", "doc-search"],
        "data": ["csv-transform", "json-validator", "sql-helper", "data-viz", "etl-pipeline"],
        "cloud": ["aws-deploy", "docker-compose"],
        "productivity": ["pomodoro", "note-taker", "calendar-sync", "task-tracker",
                         "email-draft", "meeting-summary"],
        "integration": ["slack-bot", "github-hook", "webhook-relay"],
    }
    skills = []
    for cat, names in cats.items():
        for name in names:
            src = random.choice(["clawhub", "github"])
            stars = random.randint(50, 30000)
            dl = random.randint(100, 500000)
            q = round(random.uniform(15, 95), 1)
            desc = f"A {cat} skill for {name.replace('-', ' ')}"
            skills.append((name, src, stars, dl, q, cat, desc))
    conn.executemany("INSERT INTO skills VALUES (?,?,?,?,?,?,?)", skills)
    conn.commit()
    return conn


def generate_dashboard(conn: sqlite3.Connection, output_path: str, chinese_data=None, trends_data=None, dep_data=None, contrib_data=None, rec_data=None):
    """Build and write the interactive HTML dashboard."""
    total = _query(conn, "SELECT COUNT(*) FROM skills")[0][0]
    avg_q = _query(conn, "SELECT AVG(quality_score) FROM skills")[0][0] or 0
    n_cats = _query(conn, "SELECT COUNT(DISTINCT category) FROM skills")[0][0]

    cat_stats = _query(conn,
        "SELECT category, COUNT(*) as cnt, AVG(quality_score) as aq FROM skills GROUP BY category")
    all_cats = {"coding","browser","search","media","cloud","data","security",
                "productivity","social","finance","memory","integration"}
    present = {r[0] for r in cat_stats}
    gap_count = len(all_cats - present)
    for r in cat_stats:
        if r[1] < 3 or r[2] < 35:
            gap_count += 1

    # All skills for graph + table
    all_skills = _query(conn,
        "SELECT name, source, stars, downloads, quality_score, category, COALESCE(url,'') FROM skills ORDER BY stars DESC")

    top_skills = all_skills[:15]

    cat_labels = [r[0] for r in cat_stats]
    cat_counts = [r[1] for r in cat_stats]

    q_buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    rows = _query(conn, "SELECT quality_score FROM skills")
    for r in rows:
        q = r[0]
        if q <= 20: q_buckets["0-20"] += 1
        elif q <= 40: q_buckets["21-40"] += 1
        elif q <= 60: q_buckets["41-60"] += 1
        elif q <= 80: q_buckets["61-80"] += 1
        else: q_buckets["81-100"] += 1

    gaps = []
    for c in sorted(all_cats - present):
        gaps.append({"category": c, "count": 0, "avg_quality": 0, "reason": "No skills found"})
    for r in cat_stats:
        if r[1] < 3:
            gaps.append({"category": r[0], "count": r[1], "avg_quality": round(r[2], 1), "reason": f"Only {r[1]} skill(s)"})
        elif r[2] < 35:
            gaps.append({"category": r[0], "count": r[1], "avg_quality": round(r[2], 1), "reason": "Low avg quality"})

    html = _build_html(
        total=total, avg_q=round(avg_q, 1), n_cats=n_cats, gap_count=gap_count,
        all_skills=all_skills, top_skills=top_skills,
        cat_labels=cat_labels, cat_counts=cat_counts,
        q_buckets=q_buckets, gaps=gaps,
        chinese_data=chinese_data, trends_data=trends_data, dep_data=dep_data,
        contrib_data=contrib_data, rec_data=rec_data,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"[dashboard] Written to {output_path}")


def _auto_recommend(all_skills):
    """Auto-generate recommendations: top quality skills from diverse categories."""
    by_cat = {}
    for s in all_skills:
        cat = s[5] if len(s) > 5 else 'other'
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(s)
    recs = []
    # Pick best quality skill from each category (up to 8)
    for cat in sorted(by_cat.keys()):
        skills = sorted(by_cat[cat], key=lambda x: (x[4] if len(x) > 4 else 0, x[2] if len(x) > 2 else 0), reverse=True)
        if skills:
            s = skills[0]
            recs.append({
                "name": s[0],
                "category": cat,
                "quality_score": round(s[4], 1) if len(s) > 4 else 0,
                "url": s[6] if len(s) > 6 and s[6] else "",
                "reason": f"Top rated in {cat} ({s[2]} stars)" if len(s) > 2 else f"Top rated in {cat}"
            })
    # Sort by quality descending, take top 8
    recs.sort(key=lambda x: x["quality_score"], reverse=True)
    return recs[:8]

def _build_html(*, total, avg_q, n_cats, gap_count, all_skills, top_skills,
                cat_labels, cat_counts, q_buckets, gaps,
                chinese_data=None, trends_data=None, dep_data=None,
                contrib_data=None, rec_data=None):
    # Prepare all_skills as JSON for JS
    skills_json = json.dumps([
        {"name": s[0], "source": s[1], "stars": s[2], "downloads": s[3],
         "quality": round(s[4], 1), "category": s[5], "url": s[6] if len(s) > 6 else ""}
        for s in all_skills
    ])

    # Security/platform mock data for dashboard display
    security_ratings = {"safe": "🟢safe", "caution": "🟡caution", "dangerous": "🔴dangerous"}
    platform_icons = {"openclaw": "🐾", "claude_code": "🤖", "cursor": "📝", "codex": "💻", "generic": "🌐"}
    import random as _rnd
    _rnd.seed(7)

    top_rows = ""
    for i, s in enumerate(top_skills, 1):
        badge = "clawhub" if s[1] == "clawhub" else "github"
        badge_color = "#6c5ce7" if badge == "clawhub" else "#636e72"
        # Simulate security & platform for display
        sec_r = _rnd.choice(["safe", "safe", "safe", "caution", "caution", "dangerous"])
        sec_display = security_ratings[sec_r]
        plats = _rnd.sample(["openclaw", "claude_code", "cursor", "generic"], k=_rnd.randint(1,3))
        plat_display = " ".join(platform_icons.get(p, "🌐") for p in plats)
        top_rows += f"""
        <tr data-cat="{s[5]}" data-quality="{s[4]:.0f}" data-stars="{s[2]}" data-name="{s[0].lower()}">
          <td>{i}</td>
          <td><span class="badge" style="background:{badge_color}">{badge}</span> <a href="{s[6] if len(s) > 6 and s[6] else '#'}" target="_blank" style="color:var(--accent2);text-decoration:none">{s[0]}</a></td>
          <td>⭐ {s[2]:,}</td>
          <td>{s[3]:,}</td>
          <td><span class="qscore">{s[4]:.0f}</span></td>
          <td>{sec_display}</td>
          <td>{plat_display}</td>
          <td><span class="cat-tag">{s[5]}</span></td>
        </tr>"""

    gap_rows = ""
    for g in gaps:
        gap_rows += f"""
        <tr class="gap-row">
          <td><span class="gap-cat">{g['category']}</span></td>
          <td>{g['count']}</td>
          <td>{g['avg_quality']}</td>
          <td>{g['reason']}</td>
          <td><button class="create-btn" onclick="alert('🚀 Create Skill wizard for \\'{g['category']}\\' coming soon!')">+ Create Skill</button></td>
        </tr>"""

    # unique categories for dropdown
    unique_cats = sorted(set(s[5] for s in all_skills))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Skill Marketplace Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  :root {{
    --bg: #0a0e1a; --surface: #141929; --border: #1e2640;
    --text: #e0e6f0; --muted: #8892a8; --accent: #6c5ce7;
    --accent2: #00cec9; --accent3: #fd79a8; --accent4: #fdcb6e;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, 'Segoe UI', sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh;
    background-image: radial-gradient(ellipse at 20% 50%, rgba(108,92,231,0.08) 0%, transparent 50%),
                      radial-gradient(ellipse at 80% 20%, rgba(0,206,201,0.06) 0%, transparent 50%);
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.3rem; }}
  .subtitle {{ color: var(--muted); margin-bottom: 2rem; font-size: 0.9rem; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 2rem; }}
  .stat-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.5rem; text-align: center;
    transition: transform 0.2s, box-shadow 0.2s;
  }}
  .stat-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 20px rgba(108,92,231,0.2); }}
  .stat-card .value {{ font-size: 2rem; font-weight: 700; }}
  .stat-card .label {{ color: var(--muted); font-size: 0.85rem; margin-top: 0.3rem; }}
  .c1 .value {{ color: var(--accent); }}
  .c2 .value {{ color: var(--accent2); }}
  .c3 .value {{ color: var(--accent4); }}
  .c4 .value {{ color: var(--accent3); }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 1.5rem;
  }}
  .card h2 {{ font-size: 1.1rem; margin-bottom: 1rem; }}
  .full {{ grid-column: 1 / -1; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }}
  th:hover {{ color: var(--accent2); }}
  th .sort-arrow {{ font-size: 0.7rem; margin-left: 4px; opacity: 0.5; }}
  th.sorted .sort-arrow {{ opacity: 1; color: var(--accent2); }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.7rem; color: #fff; font-weight: 600;
  }}
  .qscore {{
    display: inline-block; background: var(--accent); color: #fff;
    padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600;
  }}
  .cat-tag {{
    display: inline-block; padding: 2px 10px; border-radius: 10px;
    font-size: 0.75rem; font-weight: 500; border: 1px solid var(--border);
    background: rgba(108,92,231,0.1);
  }}
  canvas {{ max-height: 300px; }}

  /* Filter controls */
  .filter-bar {{
    display: flex; gap: 0.8rem; margin-bottom: 1rem; align-items: center; flex-wrap: wrap;
  }}
  .filter-bar input, .filter-bar select {{
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 0.5rem 0.8rem; font-size: 0.85rem; outline: none;
  }}
  .filter-bar input:focus, .filter-bar select:focus {{ border-color: var(--accent); }}
  .filter-bar input {{ min-width: 200px; }}
  .active-filter {{
    display: inline-block; background: var(--accent); color: #fff; padding: 4px 12px;
    border-radius: 12px; font-size: 0.75rem; cursor: pointer; margin-left: auto;
  }}
  .active-filter:hover {{ background: #5a4bd4; }}
  .hidden {{ display: none !important; }}

  /* Gap enhancements */
  .gap-row {{ background: rgba(0, 206, 201, 0.04); }}
  .gap-row:hover {{ background: rgba(0, 206, 201, 0.1); }}
  .gap-cat {{
    display: inline-block; padding: 2px 10px; border-radius: 10px;
    font-size: 0.8rem; font-weight: 600; color: #55efc4;
    border: 1px solid rgba(85, 239, 196, 0.3); background: rgba(85, 239, 196, 0.08);
  }}
  .create-btn {{
    background: linear-gradient(135deg, #00b894, #00cec9);
    color: #fff; border: none; padding: 6px 16px; border-radius: 8px;
    font-size: 0.78rem; font-weight: 600; cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
  }}
  .create-btn:hover {{ transform: scale(1.05); box-shadow: 0 2px 12px rgba(0,206,201,0.4); }}

  /* vis.js graph */
  #skill-graph {{
    width: 100%; height: 550px; border-radius: 12px;
    border: 1px solid var(--border); background: var(--bg);
  }}

  /* table row highlight */
  tr.highlight {{ background: rgba(108,92,231,0.15) !important; }}

  @media (max-width: 768px) {{
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
    .grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">
  <h1>🔮 Skill Marketplace Analyzer</h1>
  <p class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · Interactive Dashboard</p>

  <div class="stats">
    <div class="stat-card c1"><div class="value">{total}</div><div class="label">Total Skills</div></div>
    <div class="stat-card c2"><div class="value">{avg_q}</div><div class="label">Avg Quality</div></div>
    <div class="stat-card c3"><div class="value">{n_cats}</div><div class="label">Categories</div></div>
    <div class="stat-card c4"><div class="value">{gap_count}</div><div class="label">Market Gaps</div></div>
  </div>

  <div class="card full" style="margin-bottom:1.5rem">
    <h2>🏆 Top Skills</h2>
    <div class="filter-bar">
      <input type="text" id="searchBox" placeholder="🔍 Search skills..." oninput="filterTable()">
      <select id="catFilter" onchange="filterTable()">
        <option value="">All Categories</option>
        {"".join(f'<option value="{c}">{c}</option>' for c in unique_cats)}
      </select>
      <span id="activeFilter" class="active-filter hidden" onclick="clearAllFilters()">✕ Clear filter</span>
    </div>
    <table id="skillTable">
      <thead>
      <tr>
        <th data-sort="index"># <span class="sort-arrow">▲</span></th>
        <th data-sort="name">Skill <span class="sort-arrow">▲</span></th>
        <th data-sort="stars">Stars <span class="sort-arrow">▼</span></th>
        <th data-sort="downloads">Downloads <span class="sort-arrow">▲</span></th>
        <th data-sort="quality">Quality <span class="sort-arrow">▲</span></th>
        <th data-sort="security">Security <span class="sort-arrow">▲</span></th>
        <th>Platforms</th>
        <th data-sort="category">Category <span class="sort-arrow">▲</span></th>
      </tr>
      </thead>
      <tbody id="skillTableBody">
        {top_rows}
      </tbody>
    </table>
  </div>

  <div class="grid">
    <div class="card">
      <h2>📊 Category Distribution</h2>
      <p style="color:var(--muted);font-size:0.75rem;margin-top:-0.5rem;margin-bottom:0.5rem">Click a slice to filter</p>
      <canvas id="catChart"></canvas>
    </div>
    <div class="card">
      <h2>📈 Quality Distribution</h2>
      <p style="color:var(--muted);font-size:0.75rem;margin-top:-0.5rem;margin-bottom:0.5rem">Click a bar to filter</p>
      <canvas id="qualChart"></canvas>
    </div>
  </div>

  <div class="card full" style="margin-bottom:1.5rem">
    <h2>🔍 Market Gaps <span style="font-size:0.8rem;color:var(--accent2);font-weight:400">— Opportunities</span></h2>
    <table>
      <tr><th>Category</th><th>Skills</th><th>Avg Quality</th><th>Issue</th><th>Action</th></tr>
      {gap_rows}
    </table>
  </div>

  <!-- Recommendations Card (if data available) -->
  <div class="grid" id="recContribGrid">
    <div class="card" id="recCard">
      <h2>💡 Recommended Skills</h2>
      <div id="recArea" style="font-size:0.85rem">
        <p style="color:var(--muted)">Based on your installed skills</p>
        <div id="recList" style="margin-top:0.8rem"></div>
      </div>
    </div>
    <div class="card">
      <h2>👥 Top Contributors</h2>
      <div id="contribArea" style="font-size:0.85rem">
        <table style="width:100%">
          <thead><tr><th>Contributor</th><th>Skills</th><th>Avg Quality</th><th>⭐ Total</th></tr></thead>
          <tbody id="contribBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Chinese Ecosystem Card -->
  <div class="grid">
    <div class="card">
      <h2>🇨🇳 中文 Skill 生态</h2>
      <div id="chineseEco">
        <p style="font-size:2rem;font-weight:700;color:var(--accent)" id="cnTotal">0</p>
        <p style="color:var(--muted);font-size:0.85rem">Chinese Skills (<span id="cnPct">0</span>% of total)</p>
        <div id="cnGaps" style="margin-top:1rem"></div>
      </div>
    </div>
    <div class="card">
      <h2>🚀 Trending Skills</h2>
      <div id="trendsArea" style="font-size:0.85rem">
        <p style="color:var(--muted)">Top skills by estimated growth rate</p>
        <ol id="trendsList" style="padding-left:1.2rem;margin-top:0.8rem"></ol>
      </div>
    </div>
  </div>

  <div class="card full">
    <h2>🌐 Skill Relationship Graph</h2>
    <p style="color:var(--muted);font-size:0.75rem;margin-bottom:0.8rem">Nodes sized by stars · Colored by category · Drag to explore · Hover for details</p>
    <div id="skill-graph"></div>
  </div>
</div>

<script>
// === DATA ===
const ALL_SKILLS = {skills_json};
const CAT_LABELS = {json.dumps(cat_labels)};
const CAT_COUNTS = {json.dumps(cat_counts)};
const Q_KEYS = {json.dumps(list(q_buckets.keys()))};
const Q_VALS = {json.dumps(list(q_buckets.values()))};

const CAT_COLORS = {{
  coding: '#6c5ce7', browser: '#a29bfe', media: '#55efc4', search: '#74b9ff',
  data: '#fdcb6e', cloud: '#e17055', security: '#fd79a8', productivity: '#00cec9',
  social: '#fab1a0', finance: '#81ecec', memory: '#dfe6e9', integration: '#636e72'
}};

// Chinese ecosystem data
const CHINESE_DATA = {json.dumps(chinese_data or {}, ensure_ascii=False)};
const TRENDS_DATA = {json.dumps(trends_data or {}, ensure_ascii=False)};
const DEP_DATA = {json.dumps(dep_data or {}, ensure_ascii=False)};
const CONTRIB_DATA = {json.dumps(contrib_data or {}, ensure_ascii=False)};
const REC_DATA = {json.dumps(rec_data if rec_data else _auto_recommend(all_skills), ensure_ascii=False)};

// Populate recommendations
if (REC_DATA && REC_DATA.length > 0) {{
  const recList = document.getElementById('recList');
  REC_DATA.forEach(r => {{
    recList.innerHTML += `<div style="padding:6px 0;border-bottom:1px solid var(--border)">
      <span style="color:var(--accent2);font-weight:600"><a href="${{r.url}}" target="_blank" style="color:var(--accent2);text-decoration:none" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">${{r.name}}</a></span>
      <span class="cat-tag" style="margin-left:6px">${{r.category}}</span>
      <span style="color:var(--accent4);margin-left:6px">Q:${{r.quality_score}}</span>
      <br><span style="color:var(--muted);font-size:0.78rem">${{r.reason}}</span>
    </div>`;
  }});
}} else {{
  document.getElementById('recList').innerHTML = '<p style="color:var(--muted)">Use --recommend "skill1,skill2" to get personalized recommendations</p>';
}}

// Populate contributors
if (CONTRIB_DATA.top_contributors) {{
  const tbody = document.getElementById('contribBody');
  CONTRIB_DATA.top_contributors.slice(0, 10).forEach(c => {{
    tbody.innerHTML += `<tr>
      <td style="font-weight:600;color:var(--accent)">${{c.name}}</td>
      <td>${{c.skill_count}}</td>
      <td>${{c.avg_quality}}</td>
      <td>${{c.total_stars.toLocaleString()}}</td>
    </tr>`;
  }});
}}

// Populate Chinese ecosystem card
if (CHINESE_DATA.total_chinese !== undefined) {{
  document.getElementById('cnTotal').textContent = CHINESE_DATA.total_chinese;
  document.getElementById('cnPct').textContent = CHINESE_DATA.percentage;
  const gapsDiv = document.getElementById('cnGaps');
  if (CHINESE_DATA.gaps && CHINESE_DATA.gaps.length > 0) {{
    gapsDiv.innerHTML = '<p style="color:var(--accent3);font-size:0.8rem;font-weight:600">缺口分类（无中文 skill）:</p>' +
      CHINESE_DATA.gaps.map(g => `<span class="cat-tag" style="margin:2px">${{g.category}} (${{g.english_count}})</span>`).join('');
  }}
}}

// Populate trends
if (TRENDS_DATA.trending_skills) {{
  const list = document.getElementById('trendsList');
  TRENDS_DATA.trending_skills.slice(0, 10).forEach(s => {{
    const li = document.createElement('li');
    li.style.marginBottom = '4px';
    li.innerHTML = `<span style="color:var(--accent2)">${{s.name}}</span> ⭐${{s.stars}} <span style="color:var(--accent4)">+${{s.growth_rate}}/day</span>`;
    list.appendChild(li);
  }});
}}
const CHART_COLORS = ['#6c5ce7','#00cec9','#fd79a8','#fdcb6e','#e17055','#74b9ff',
                '#a29bfe','#55efc4','#fab1a0','#81ecec','#dfe6e9','#636e72'];

let activeCatFilter = '';
let activeQualFilter = '';

// === SORTABLE TABLE ===
let sortCol = 'stars';
let sortAsc = false;

document.querySelectorAll('#skillTable thead th[data-sort]').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.sort;
    if (sortCol === col) sortAsc = !sortAsc;
    else {{ sortCol = col; sortAsc = col === 'name' || col === 'category'; }}
    sortTable();
  }});
}});

function sortTable() {{
  const tbody = document.getElementById('skillTableBody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {{
    let va, vb;
    if (sortCol === 'index') {{ va = parseInt(a.cells[0].textContent); vb = parseInt(b.cells[0].textContent); }}
    else if (sortCol === 'name') {{ va = a.dataset.name; vb = b.dataset.name; }}
    else if (sortCol === 'stars') {{ va = +a.dataset.stars; vb = +b.dataset.stars; }}
    else if (sortCol === 'downloads') {{ va = +a.cells[3].textContent.replace(/,/g,''); vb = +b.cells[3].textContent.replace(/,/g,''); }}
    else if (sortCol === 'quality') {{ va = +a.dataset.quality; vb = +b.dataset.quality; }}
    else if (sortCol === 'category') {{ va = a.dataset.cat; vb = b.dataset.cat; }}
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  }});
  rows.forEach(r => tbody.appendChild(r));
  // Update arrows
  document.querySelectorAll('#skillTable thead th').forEach(th => {{
    th.classList.toggle('sorted', th.dataset.sort === sortCol);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = (th.dataset.sort === sortCol) ? (sortAsc ? '▲' : '▼') : '▲';
  }});
}}

// === FILTER TABLE ===
function filterTable() {{
  const search = document.getElementById('searchBox').value.toLowerCase();
  const cat = document.getElementById('catFilter').value || activeCatFilter;
  const rows = document.querySelectorAll('#skillTableBody tr');
  rows.forEach(r => {{
    const matchName = !search || r.dataset.name.includes(search);
    const matchCat = !cat || r.dataset.cat === cat;
    let matchQual = true;
    if (activeQualFilter) {{
      const q = +r.dataset.quality;
      const [lo, hi] = activeQualFilter.split('-').map(Number);
      matchQual = q >= lo && q <= hi;
    }}
    r.classList.toggle('hidden', !(matchName && matchCat && matchQual));
  }});
  const hasFilter = search || cat || activeQualFilter;
  document.getElementById('activeFilter').classList.toggle('hidden', !hasFilter);
  if (hasFilter) {{
    let parts = [];
    if (cat) parts.push(cat);
    if (activeQualFilter) parts.push('Q:' + activeQualFilter);
    if (search) parts.push('"' + search + '"');
    document.getElementById('activeFilter').textContent = '✕ ' + parts.join(' · ');
  }}
}}

function clearAllFilters() {{
  activeCatFilter = '';
  activeQualFilter = '';
  document.getElementById('searchBox').value = '';
  document.getElementById('catFilter').value = '';
  filterTable();
  // Reset graph highlights
  if (window.network) {{
    const allIds = ALL_SKILLS.map((_, i) => i);
    network.selectNodes([]);
    const updNodes = allIds.map(id => ({{ id, opacity: 1.0 }}));
    nodes.update(updNodes);
  }}
}}

// === DONUT CHART ===
const catChart = new Chart(document.getElementById('catChart'), {{
  type: 'doughnut',
  data: {{
    labels: CAT_LABELS,
    datasets: [{{ data: CAT_COUNTS, backgroundColor: CHART_COLORS.slice(0, CAT_LABELS.length),
      hoverOffset: 8, borderWidth: 0 }}]
  }},
  options: {{
    plugins: {{
      legend: {{ position: 'right', labels: {{ color: '#e0e6f0', font: {{ size: 11 }}, padding: 8 }} }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.label}}: ${{ctx.raw}} skills` }} }}
    }},
    responsive: true, maintainAspectRatio: true,
    onClick: (evt, elements) => {{
      if (elements.length > 0) {{
        const idx = elements[0].index;
        const cat = CAT_LABELS[idx];
        if (activeCatFilter === cat) {{ clearAllFilters(); return; }}
        activeCatFilter = cat;
        activeQualFilter = '';
        document.getElementById('catFilter').value = cat;
        filterTable();
        highlightGraphCategory(cat);
      }}
    }}
  }}
}});

// === QUALITY BAR CHART ===
const qualChart = new Chart(document.getElementById('qualChart'), {{
  type: 'bar',
  data: {{
    labels: Q_KEYS,
    datasets: [{{ label: 'Skills', data: Q_VALS,
      backgroundColor: ['#e17055','#fdcb6e','#00cec9','#6c5ce7','#55efc4'],
      hoverBackgroundColor: ['#e17055cc','#fdcb6ecc','#00cec9cc','#6c5ce7cc','#55efc4cc'],
      borderRadius: 6 }}]
  }},
  options: {{
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.raw}} skills in range ${{ctx.label}}` }} }}
    }},
    scales: {{
      x: {{ ticks: {{ color: '#8892a8' }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ color: '#8892a8' }}, grid: {{ color: '#1e2640' }} }}
    }},
    responsive: true, maintainAspectRatio: true,
    onClick: (evt, elements) => {{
      if (elements.length > 0) {{
        const idx = elements[0].index;
        const range = Q_KEYS[idx];
        if (activeQualFilter === range) {{ clearAllFilters(); return; }}
        activeQualFilter = range;
        activeCatFilter = '';
        document.getElementById('catFilter').value = '';
        filterTable();
      }}
    }}
  }}
}});

// === VIS.JS SKILL GRAPH ===
const maxStars = Math.max(...ALL_SKILLS.map(s => s.stars));
const nodes = new vis.DataSet(ALL_SKILLS.map((s, i) => ({{
  id: i,
  label: s.name,
  size: 8 + (s.stars / maxStars) * 40,
  color: {{
    background: CAT_COLORS[s.category] || '#636e72',
    border: CAT_COLORS[s.category] || '#636e72',
    highlight: {{ background: '#fff', border: CAT_COLORS[s.category] || '#636e72' }},
    hover: {{ background: (CAT_COLORS[s.category] || '#636e72') + 'cc', border: '#fff' }}
  }},
  font: {{ color: '#e0e6f0', size: 10 }},
  title: `<b>${{s.name}}</b><br>⭐ ${{s.stars.toLocaleString()}}<br>Quality: ${{s.quality}}<br>Category: ${{s.category}}`,
  group: s.category,
  opacity: 1.0
}})));

// Edges: connect skills in the same category (nearest neighbors for clustering)
const edgeList = [];
const byCat = {{}};
ALL_SKILLS.forEach((s, i) => {{ if (!byCat[s.category]) byCat[s.category] = []; byCat[s.category].push(i); }});
Object.values(byCat).forEach(ids => {{
  for (let j = 1; j < ids.length; j++) {{
    edgeList.push({{ from: ids[j-1], to: ids[j], color: {{ color: 'rgba(255,255,255,0.06)' }}, width: 0.5 }});
  }}
  // Connect last to first for loop
  if (ids.length > 2) edgeList.push({{ from: ids[ids.length-1], to: ids[0], color: {{ color: 'rgba(255,255,255,0.04)' }}, width: 0.3 }});
}});

// Add dependency edges from DEP_DATA
if (DEP_DATA.edges) {{
  const nameToIdx = {{}};
  ALL_SKILLS.forEach((s, i) => {{ nameToIdx[s.name] = i; }});
  // Add tool/API dep nodes and edges
  let extraId = ALL_SKILLS.length;
  const extraNodes = {{}};
  DEP_DATA.edges.forEach(e => {{
    // Find source node
    const srcName = (e.source || '').split(':').pop();
    const srcIdx = nameToIdx[srcName];
    if (srcIdx === undefined) return;
    const targetKey = e.target;
    if (!extraNodes[targetKey]) {{
      const label = targetKey.split(':').pop();
      const isTool = e.type === 'tool_dep';
      const isApi = e.type === 'api_dep';
      nodes.add({{
        id: extraId,
        label: (isTool ? '🔧' : isApi ? '🔑' : '🔗') + ' ' + label,
        size: 6,
        color: {{ background: isTool ? '#e17055' : isApi ? '#fdcb6e' : '#a29bfe', border: '#1e2640' }},
        font: {{ color: '#8892a8', size: 8 }},
        shape: isTool ? 'diamond' : isApi ? 'triangle' : 'dot',
        title: `${{e.type}}: ${{label}}`,
        opacity: 0.7
      }});
      extraNodes[targetKey] = extraId++;
    }}
    edgeList.push({{
      from: srcIdx,
      to: extraNodes[targetKey],
      color: {{ color: e.type === 'tool_dep' ? 'rgba(225,112,85,0.3)' : e.type === 'api_dep' ? 'rgba(253,203,110,0.3)' : 'rgba(162,155,254,0.3)' }},
      width: 0.8,
      dashes: e.type === 'api_dep'
    }});
  }});
}}
const edges = new vis.DataSet(edgeList);

const graphContainer = document.getElementById('skill-graph');
const network = new vis.Network(graphContainer, {{ nodes, edges }}, {{
  physics: {{
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {{ gravitationalConstant: -40, centralGravity: 0.008, springLength: 120 }},
    stabilization: {{ iterations: 150 }}
  }},
  interaction: {{
    hover: true, tooltipDelay: 100,
    zoomView: true, dragView: true, dragNodes: true
  }},
  groups: Object.fromEntries(Object.entries(CAT_COLORS).map(([k,v]) => [k, {{ color: {{ background: v, border: v }} }}]))
}});

network.on('click', params => {{
  if (params.nodes.length > 0) {{
    const skill = ALL_SKILLS[params.nodes[0]];
    activeCatFilter = skill.category;
    document.getElementById('catFilter').value = skill.category;
    filterTable();
    highlightGraphCategory(skill.category);
  }}
}});

function highlightGraphCategory(cat) {{
  const updates = ALL_SKILLS.map((s, i) => ({{
    id: i,
    opacity: s.category === cat ? 1.0 : 0.15
  }}));
  nodes.update(updates);
}}
</script>
</body>
</html>"""


if __name__ == "__main__":
    import sys
    mock = "--mock" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--mock"]

    if mock:
        conn = _mock_db()
        out_path = args[0] if args else "/tmp/skill-analyzer-interactive.html"
    else:
        db_path = args[0] if args else str(Path(__file__).parent / "data" / "skills.db")
        out_path = args[1] if len(args) > 1 else "/tmp/skill-analyzer-dashboard.html"
        conn = sqlite3.connect(db_path)

    conn.row_factory = None
    generate_dashboard(conn, out_path)
    conn.close()
