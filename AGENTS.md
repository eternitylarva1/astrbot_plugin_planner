# AGENTS.md - astrbot_plugin_planner

> Agentic coding guidelines for the astrbot_plugin_planner project.
> This is an AstrBot plugin that acts as a frontend for the Schedule App backend API.

## Project Overview

- **Type**: AstrBot plugin (Python 3.12)
- **Purpose**: Intelligent schedule assistant with natural language creation, AI task breakdown, and visualization
- **Architecture**: Plugin frontend + Schedule App backend (separate service)
- **Framework**: AstrBot API
- **Data Storage**: Schedule App's SQLite database (not local JSON)

## Architecture

```
┌─────────────────────┐      ┌──────────────────────┐
│   AstrBot Plugin     │ API  │   Schedule App        │
│   (main.py)         │─────▶│   Backend            │
│                     │      │   (aiohttp + SQLite)  │
│  - Commands         │      │                      │
│  - API Client       │      │  - Events CRUD       │
│  - Screenshot       │      │  - Goals             │
└─────────────────────┘      │  - LLM endpoints     │
                             │  - Notes/Expenses     │
                             └──────────────────────┘
```

## Dependencies

```bash
pip install -r requirements.txt
```

Requirements: `aiohttp` (for API client)

## Build/Lint/Test Commands

### Type Checking
```bash
pyright
```

## Code Style Guidelines

### General
- **Python Version**: 3.12
- **Type Checking Mode**: basic (pyright)
- **Encoding**: UTF-8 for all files

### Imports
```python
# Standard library first
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# AstrBot imports
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# Relative imports within package
from .services.api_client import init_api_client, get_api_client
```

### Naming Conventions
| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `ApiClient` |
| Functions/variables | snake_case | `get_events()`, `_parse_date_filter()` |

### API Client Pattern
All backend communication goes through `services/api_client.py`:
```python
self.api = get_api_client()
events = await self.api.get_events("today")
await self.api.create_event(event_data)
```

## File Structure
```
astrbot_plugin_planner/
├── main.py                  # Plugin entry, commands
├── metadata.yaml            # Plugin metadata
├── _conf_schema.json       # WebUI config schema
├── pyrightconfig.json      # Type checking config
├── requirements.txt        # Dependencies
├── services/
│   └── api_client.py      # Schedule App API client
└── models/                 # (simplified, data comes from API)
```

## Key Constraints

1. **Schedule App Backend Required**: The plugin cannot function without the Schedule App backend running
2. **API Base URL Configuration**: Must configure `schedule_api_base` in plugin settings
3. **Session Isolation**: Not implemented in v2 (Schedule App handles this internally)

## Configuration Schema
Config keys in `_conf_schema.json`:
- `schedule_api_base`: Backend API URL (default: http://localhost:8080)
- `frontend_url`: Frontend URL for screenshots (default: http://localhost:8080)
- `enable_screenshot`: Enable/disable screenshot feature

## Commands

| Command | Description |
|---------|-------------|
| `/计划` | Create schedule with natural language |
| `/日程` | View schedules (today/tomorrow/week) |
| `/图表` | View visual chart screenshot |
| `/完成` | Mark task as complete |
| `/取消` | Delete/cancel schedule |
| `/待办` | List pending tasks |
| `/ai规划` | AI-powered goal planning |
| `/拆解` | Task breakdown |
| `/统计` | View completion statistics |
| `/帮助` | Show help |

## Version Updates
When making changes:
1. Update `metadata.yaml` version
2. Update `CHANGELOG.md`
3. Run tests if available
