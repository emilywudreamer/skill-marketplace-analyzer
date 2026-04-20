---
name: skill-marketplace-analyzer
description: Analyze AI agent skills across marketplaces with security scanning and compatibility checking
version: 0.3.0
---

# Skill Marketplace Analyzer

Scan, analyze, and compare AI agent skills from ClawHub, GitHub, and Anthropic repositories.

## Commands

```bash
# Quick report with mock data
python3 analyzer.py --mock --report

# Scan all sources and generate dashboard
python3 analyzer.py --scan all --report --gaps --dashboard

# Scan Anthropic skills only
python3 analyzer.py --scan anthropic --report
```

## Features

- Multi-source scanning (ClawHub, GitHub, Anthropic)
- Quality scoring (0-100) with weighted criteria
- Security scanning — detects dangerous code patterns
- Cross-platform compatibility detection (OpenClaw/Claude Code/Cursor/Codex)
- Category classification (12+ categories)
- Market gap analysis
- Interactive HTML dashboard with vis.js graph
- CLI text reports

## API

```python
from analyzer import scan_security, check_compatibility

# Security scan a skill directory
result = scan_security("/path/to/skill")
# → {"score": 85, "risks": [...], "rating": "caution"}

# Check platform compatibility
compat = check_compatibility("/path/to/skill")
# → {"platforms": ["openclaw", "claude_code"], "format_valid": True, "issues": []}
```
