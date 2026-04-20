# Skill Marketplace Analyzer

Analyze, compare, and discover AI agent skills across multiple marketplaces.

## Features

- **Multi-source scanning**: ClawHub, GitHub, Anthropic skills repositories
- **Quality scoring**: Weighted scoring based on documentation, references, scripts, recency
- **Category classification**: Auto-classify skills into 12+ categories
- **Market gap analysis**: Find underserved categories and opportunities
- **Security scanning**: Detect dangerous patterns in skill code (filesystem ops, code injection, credential leaks, etc.)
- **Cross-platform compatibility**: Check if skills work on OpenClaw, Claude Code, Cursor, Codex
- **Interactive dashboard**: Dark starry theme with vis.js graph, charts, sortable tables
- **Text reports**: CLI-friendly analysis output

## Usage

```bash
# Load mock data and generate report
python3 analyzer.py --mock --report

# Scan all sources
python3 analyzer.py --scan all --report

# Scan Anthropic skills specifically
python3 analyzer.py --scan anthropic --report

# Generate interactive dashboard
python3 analyzer.py --mock --dashboard /tmp/dashboard.html

# Find market gaps
python3 analyzer.py --mock --gaps

# Full pipeline
python3 analyzer.py --scan all --report --gaps --dashboard
```

## Security Scanner

The `scan_security()` function analyzes skill directories for:
- 🔴 **filesystem_danger**: `rm -rf`, `shutil.rmtree`, `os.remove`
- 🔴 **code_injection**: `exec()`, `eval()`, `compile()`
- 🔴 **shell_injection**: `subprocess.call(shell=True)`
- 🔴 **credential_leak**: Hardcoded API keys/tokens
- 🟡 **network_access**: HTTP requests to external URLs
- 🟡 **file_write**: File write operations

Ratings: 🟢 safe | 🟡 caution | 🔴 dangerous

## Compatibility Checker

The `check_compatibility()` function detects platform-specific features:
- **OpenClaw**: `memory_search`, `sessions_spawn`, `message tool`, `feishu_*`
- **Claude Code**: `execute_command`, `manage_process`
- **Cursor**: `codebase_search`, `file_search`
- **Generic**: No platform-specific features detected

## Data Sources

| Source | Command | Description |
|--------|---------|-------------|
| ClawHub | `--scan clawhub` | Official OpenClaw skill marketplace |
| GitHub | `--scan github` | Public repos with SKILL.md |
| Anthropic | `--scan anthropic` | anthropics/skills repository |
| All | `--scan all` | All sources combined |

## Architecture

- `analyzer.py` — Core engine: scanning, scoring, classification, security, compatibility
- `dashboard_generator.py` — Interactive HTML dashboard generator
- `data/skills.db` — SQLite database for skill data
