# PRD: AI Agent Skill Marketplace 分析工具

> 银月（产品经理）| 2026-04-17 | v1.0

---

## 1. 项目背景

Agent Skill 生态正在快速扩张。当前主要平台：

| 平台 | 规模 | 特点 |
|------|------|------|
| **ClawHub** (clawhub.ai) | 5400+ skills | OpenClaw 官方 registry，有 star 数和安装量 |
| **SkillsMP** (skillsmp.com) | 700,000+ skills | 从 GitHub 聚合，支持职业分类和质量指标 |
| **Agensi** (agensi.io) | 付费市场 | 支持 Claude Code / OpenClaw / Codex 等 20+ agents |
| **agentskill.sh** | 未知 | 快速发现和安装 |
| **GitHub** (skill-md topic) | 大量散落 repo | alirezarezvani/claude-skills (232+ skills)、VoltAgent/awesome-openclaw-skills (5400+) |

**问题：** 目前没有一个统一工具能跨平台分析 skill 生态的热度、质量、缺口和趋势。SkillsMP 最接近但只做索引聚合，不做深度分析。

## 2. 目标用户

1. **Skill 开发者** — 找到市场缺口，决定做什么 skill
2. **Agent 用户** — 找到高质量 skill，避免踩坑
3. **Emily（我们）** — 了解生态，发现投资/开发机会

## 3. 核心功能

### 3.1 数据抓取

| 数据源 | 方式 | 获取数据 |
|--------|------|----------|
| ClawHub | clawhub.ai 页面抓取 / GitHub API (openclaw/clawhub repo) | skill 名称、作者、star 数、安装量、描述、分类 |
| GitHub | GitHub Search API (`topic:skill-md`, `SKILL.md in:path`) | repo star/fork/issues、最近更新、SKILL.md 内容 |
| awesome 列表 | VoltAgent/awesome-openclaw-skills | 分类索引 |

### 3.2 分类与标签系统

自动分类（基于 SKILL.md 内容和描述关键词）：

```
coding      — 代码生成、review、重构
browser     — 浏览器自动化、网页抓取
search      — 搜索引擎、知识检索
media       — 图片/视频/音频生成
cloud       — 云服务、部署、DevOps
data        — 数据分析、数据库
security    — 安全审计、渗透测试
productivity — 日历、邮件、任务管理
social      — 社交媒体、内容发布
finance     — 交易、市场分析
memory      — Agent 记忆、知识图谱
integration — 第三方 API 集成
```

### 3.3 热度排名与趋势

- **热度评分** = `stars × 2 + installs × 1 + recent_commits × 3`（可配置权重）
- **趋势分析**：对比 7 天 / 30 天数据变化，发现增长最快的 skill 和类别
- **历史快照**：每日抓取存档，支持时间线对比

### 3.4 质量评分

| 维度 | 权重 | 评分标准 |
|------|------|----------|
| SKILL.md 完整度 | 30% | 有无 description、usage、examples、references |
| 文档质量 | 20% | README 长度、结构化程度 |
| 活跃度 | 20% | 最近 commit 时间、issue 响应 |
| 社区信号 | 15% | star 数、fork 数、使用者反馈 |
| 安全性 | 15% | 有无 scripts/、权限声明、是否执行外部命令 |

输出：0-100 分 + 等级（A/B/C/D/F）

### 3.5 市场缺口发现

策略：
1. 收集用户需求信号（GitHub issues 中的 "looking for skill"、Reddit 讨论）
2. 对比已有 skill 的类别分布，找到覆盖薄弱的领域
3. 分析竞品平台（Agensi、SkillsMP）的类别，找到 ClawHub 缺失的
4. 输出「需求-供给」差距报告

### 3.6 Dashboard 可视化

单页 HTML，深色主题（与 MemCare dashboard 风格一致）：

- **概览卡片**：总 skill 数、平均质量分、本周新增、热门类别
- **排行榜**：Top 20 热门 skills、Top 20 高质量 skills、Top 20 增长最快
- **分类气泡图**：各类别 skill 数量和平均热度
- **趋势折线图**：按类别的增长曲线
- **缺口热力图**：需求强度 vs 供给数量
- **质量分布直方图**：整体质量分布

## 4. 技术方案

### 4.1 架构

```
analyzer.py (CLI 入口)
├── scrapers/
│   ├── clawhub.py      — ClawHub 数据抓取
│   ├── github.py       — GitHub API 抓取
│   └── awesome.py      — awesome 列表解析
├── analysis/
│   ├── classifier.py   — 自动分类
│   ├── scorer.py       — 质量评分
│   ├── trends.py       — 趋势分析
│   └── gaps.py         — 缺口发现
├── storage/
│   └── db.py           — SQLite 存储层
├── dashboard/
│   ├── generator.py    — HTML 生成
│   └── template.html   — Dashboard 模板
└── data/
    └── skills.db       — SQLite 数据库
```

### 4.2 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.10+ | 生态丰富，快速开发 |
| HTTP | requests + httpx | GitHub API 需要异步 |
| 数据库 | SQLite | 零依赖，单文件，够用 |
| 图表 | Chart.js（内嵌 CDN） | 无需构建，单 HTML |
| 分类 | 关键词匹配 + 简单 NLP | 先做规则，后续可加 LLM |
| 定时 | cron / openclaw cron | 每天凌晨 3:00 抓取 |

### 4.3 数据模型

```sql
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    author TEXT,
    source TEXT,           -- 'clawhub' | 'github'
    source_url TEXT,
    description TEXT,
    category TEXT,
    tags TEXT,              -- JSON array
    stars INTEGER DEFAULT 0,
    installs INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    last_updated TEXT,
    quality_score REAL,
    quality_grade TEXT,
    hot_score REAL,
    skill_md_content TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE snapshots (
    skill_id TEXT,
    date TEXT,
    stars INTEGER,
    installs INTEGER,
    hot_score REAL,
    PRIMARY KEY (skill_id, date)
);
```

## 5. CLI 接口

```bash
# 抓取最新数据
python analyzer.py --scan [--source clawhub|github|all]

# 生成文字报告
python analyzer.py --report [--top 20] [--category coding]

# 生成 HTML dashboard
python analyzer.py --dashboard [--output dashboard.html]

# 发现市场缺口
python analyzer.py --gaps [--verbose]

# 质量审计单个 skill
python analyzer.py --audit <skill-name>

# 趋势对比
python analyzer.py --trends [--days 30] [--category all]
```

## 6. 竞品分析

| 竞品 | 做了什么 | 没做什么 | 我们的优势 |
|------|----------|----------|------------|
| **SkillsMP** (skillsmp.com) | 700K+ skill 索引，职业分类，搜索 | 无质量评分，无趋势分析，无缺口发现 | 深度分析 + 质量评分 |
| **VoltAgent/awesome-openclaw-skills** | 5400+ skill 分类列表 | 静态列表，无评分，无趋势 | 动态更新 + 多维分析 |
| **Agensi** (agensi.io) | 付费 skill 市场，跨平台 | 面向卖家，不做生态分析 | 我们做买家视角的分析 |
| **alirezarezvani/claude-skills** | 232+ curated skills，多平台同步 | 单 repo curated，非生态分析 | 全生态扫描 |
| **Zerone Skill Market** | 发现+安装工具 | 无分析功能 | 分析 > 安装 |

**结论：目前没有人做 "skill 生态分析" 这件事。** 最接近的是 SkillsMP 的索引，但它只是搜索引擎，不做质量/趋势/缺口分析。这是一个清晰的空白点。

## 7. MVP 范围（Phase 1）

**2 周交付：**

1. ✅ ClawHub 数据抓取（页面解析 + GitHub API）
2. ✅ GitHub skill-md topic 抓取
3. ✅ 自动分类（关键词规则）
4. ✅ 热度评分 + 质量评分
5. ✅ CLI report 输出
6. ✅ 单页 HTML Dashboard（深色星空主题）

**Phase 2（后续）：**

- 趋势分析（需要至少 7 天数据积累）
- 市场缺口发现（需要需求信号数据）
- LLM 辅助分类
- 每日自动更新 + 通知

## 8. 成功指标

- 能抓取 1000+ skills 的数据
- 分类准确率 > 80%
- Dashboard 生成时间 < 30 秒
- Emily 觉得有用 👆

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| ClawHub 无公开 API | 优先用 GitHub repo 数据，页面抓取做备选 |
| GitHub API rate limit | 使用 token，分批抓取，本地缓存 |
| 分类不准 | 先用规则兜底，后续加 LLM |
| 数据量大 | SQLite 够用，后续可迁移 |

---

*银月，完毕。交给南宫婉拆解技术任务。*
