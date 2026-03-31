# AGENTS.md - astrbot_plugin_planner

> Agentic coding guidelines for the astrbot_plugin_planner project.
> This is an AstrBot plugin for natural language task planning with scheduling, reminders, and visualization.

## Project Overview

- **Type**: AstrBot plugin (Python 3.12)
- **Purpose**: Intelligent task planner with natural language creation, scheduling, reminders, and habit learning
- **Framework**: AstrBot API
- **Data Storage**: JSON files (tasks.json, learning.json, etc.)

## Build/Lint/Test Commands

### Type Checking
```bash
# Run pyright type checker
pyright

# Single file
pyright main.py
```

### Testing
```bash
# Run all tests
python -m pytest tests/

# Run all tests (unittest style)
python -m unittest discover -s tests

# Run specific test file
python -m unittest tests.test_planner_fixes

# Run single test case
python -m unittest tests.test_time_parser.TestTimeParserNoon.test_noon_one_oclock

# Run single test method
python -m pytest tests/test_time_parser.py::TestTimeParserRegression::test_colloquial_half_hour -v
```

### Preview/Development
```bash
# Generate HTML preview (no browser needed)
python scripts/render_preview.py

# With specific style
python scripts/render_preview.py --style card
python scripts/render_preview.py --style compact

# Export as PNG (requires playwright)
pip install playwright && playwright install chromium
python scripts/render_preview.py --style timeline --png
```

### Dependencies
```bash
pip install -r requirements.txt
```

## Code Style Guidelines

### General
- **Python Version**: 3.12 (enforced via pyrightconfig.json)
- **Type Checking Mode**: basic (pyright)
- **Encoding**: UTF-8 for all files
- **Line Endings**: LF (git managed)

### Imports
```python
# Standard library first
import asyncio
import re
import time
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any

# Third-party
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api import logger

# Relative imports within package
from .services.storage_service import StorageService
from .services.task_service import TaskService
from .models.task import Task
from .utils.time_parser import TimeParser
```

### Naming Conventions
| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `class TaskService`, `class TimeParser` |
| Functions/variables | snake_case | `parse_duration()`, `_pending_tasks` |
| Private methods | _prefix | `_prepare_task_creation()`, `_filter_tasks_by_session()` |
| Constants | UPPER_SNAKE_CASE | `MAX_DAILY_MINUTES` |
| Dataclass fields | snake_case | `duration_minutes`, `session_origin` |

### Type Annotations
- Use `Optional[X]` instead of `X | None` for compatibility
- Use `List[X]`, `Dict[K, V]` from typing
- Annotate all function parameters and return types
- Use `# type: ignore` sparingly, never use `# type: ignore[all]`

### Dataclass Models
```python
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    start_time: Optional[datetime] = None
    duration_minutes: int = 60
    status: str = "pending"
    
    def to_dict(self) -> dict:
        d = asdict(self)
        if self.start_time:
            d["start_time"] = self.start_time.isoformat()
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        if d.get("start_time"):
            d["start_time"] = datetime.fromisoformat(d["start_time"])
        return cls(**d)
```

### Async Patterns
```python
# Use IsolatedAsyncioTestCase for async tests
class TestPlannerFixes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plugin = await create_plugin()
    
    async def test_something(self):
        result = await self.plugin.some_method()
        self.assertEqual(result, expected)

# Always use async with locks
async with self._lock:
    # operations

# Never use bare except in async code
try:
    await something()
except SpecificException as e:
    logger.error(f"Error: {e}")
```

### Error Handling
```python
# Good: specific exception handling with logging
try:
    result = await self.storage.read_json(file_path)
except json.JSONDecodeError as e:
    logger.error(f"JSON decode error in {file_path}: {e}")
    return {}
except Exception as e:
    logger.error(f"Error reading {file_path}: {e}")
    raise

# Bad: empty catch blocks
try:
    something()
except:
    pass

# Good: async-safe error propagation
async def _start_webui_async(self):
    try:
        await self._webui_server.start()
    except Exception as e:
        logger.error(f"Failed to start WebUI server: {e}")
        raise  # Re-raise to let caller handle
```

### Docstrings
```python
@filter.command("计划", alias={"添加任务", "新建任务"})
async def create_task(self, event: AstrMessageEvent) -> MessageEventResult:
    """创建新任务
    
    用法：
    /计划 明天下午写代码 2小时
    /计划 明天9点开会 1小时
    /计划 每天早上运动
    """
    ...

def _strip_cmd(text: str, *aliases: str) -> str:
    """移除消息开头的指令词，返回剩余部分。"""
    ...
```

### Decorator Usage (AstrBot)
```python
from astrbot.api.event import filter

@filter.command("命令名", alias={"别名1", "别名2"})
async def handler(self, event: AstrMessageEvent) -> MessageEventResult:
    yield event.plain_result("response")
    return

@filter llm_tool("tool_name")
async def llm_handler(self, ...):
    ...
```

## Architecture Patterns

### Service Layer
- `StorageService`: JSON file persistence with async locks
- `TaskService`: Task CRUD operations
- `LearningService`: User habit learning
- `ReminderService`: APScheduler-based reminders

### Plugin Entry Point
```python
from astrbot.api.star import Star, register

@register(
    "plugin_id",
    "author",
    """Description""",
    "1.0.0",
    "https://github.com/repo",
)
class PlannerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # Initialize services
```

### Session-Based State
- Use `event.unified_msg_origin` as session identifier
- Filter tasks by session to avoid cross-session interference

## Testing Guidelines

### Mocking AstrBot
```python
def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    sys.modules["astrbot"] = astrbot
    
    api = types.ModuleType("astrbot.api")
    api.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        error=lambda *a, **k: None
    )
    sys.modules["astrbot.api"] = api
```

### Fake Event Object
```python
class _FakeEvent:
    def __init__(self, origin: str = "test-session"):
        self.unified_msg_origin = origin
        self.message_str = ""
```

## File Structure
```
astrbot_plugin_planner/
├── main.py                  # Plugin entry, commands, LLM tools
├── metadata.yaml            # Plugin metadata (version, author)
├── _conf_schema.json        # WebUI config schema
├── pyrightconfig.json       # Type checking config
├── requirements.txt         # Dependencies
├── utils/
│   ├── time_parser.py       # Time/duration parsing
│   └── visualizer.py        # HTML schedule rendering
├── models/
│   └── task.py              # Task, LearningData dataclasses
├── services/
│   ├── storage_service.py   # JSON persistence
│   ├── task_service.py      # Task CRUD
│   ├── reminder_service.py  # APScheduler reminders
│   ├── learning_service.py  # Habit learning
│   ├── llm_service.py      # Independent LLM service (task breakdown)
│   └── astrbot_scheduler_adapter.py
├── handlers/                # (reserved)
├── webui/                   # WebUI server
├── tests/
│   ├── test_time_parser.py
│   ├── test_planner_fixes.py
│   └── test_remind_default_sync.py
└── scripts/
    ├── render_preview.py    # HTML preview generation
    └── send_msg.py          # NapCat message sending script
```

## Key Constraints

1. **No astrbot imports in utils/time_parser.py** - This module must remain framework-independent for testing
2. **parse_duration returns Optional[int]**, not tuple - Don't mix plugin and test versions
3. **Pending tasks use time.perf_counter()** for timeout tracking on Windows
4. **Session isolation** - Always filter by `event.unified_msg_origin`
5. **Async everywhere** - All service methods are async

## Configuration Schema
Config keys in `_conf_schema.json`:
- `timeout_seconds`: Pending task timeout (default: 120)
- `remind_before`: Minutes before reminder (default: 10)
- `auto_plan_on_missing_time`: Auto-fill missing time (default: true)
- `avoid_past_time`: Avoid past times in AI planning (default: true)
- `habit_planning_enabled`: Enable habit learning (default: true)
- `habit_weight`: 0-1, higher = more habit-based (default: 0.7)

### LLM Configuration (Independent from AstrBot)
The WebUI can use its own LLM configuration for task breakdown:
- `llm_api_base`: LLM API base URL (e.g., `https://api.openai.com/v1`)
- `llm_api_key`: API key for the LLM service
- `llm_model`: Model name (e.g., `gpt-4o-mini`)

### LLM Service (`services/llm_service.py`)
Independent LLM service that doesn't rely on AstrBot:
- Uses OpenAI-compatible API format
- Direct HTTP calls via aiohttp
- Configurable via `_conf_schema.json`

## Version Updates
When making changes:
1. Update `metadata.yaml` version
2. Update `CHANGELOG.md`
3. Run tests before commit
4. Push immediately (don't batch commits)

## User Notification (NapCat)

When the AI agent needs user to perform manual actions (e.g., restart plugin, enable feature, confirm operation), use the NapCat script to send notification.

### NapCat Configuration
- **Script**: `scripts/send_msg.py`
- **HTTP API URL**: `http://127.0.0.1:3000`
- **Target QQ**: `2674610176`

### Usage
```bash
# Check connection
python scripts/send_msg.py --check

# Send private message
python scripts/send_msg.py <QQ号> <消息>
python scripts/send_msg.py 2674610176 你好
```

### When to Notify User
Notify user via NapCat when:
- Plugin code has been updated and needs manual reload via AstrBot admin panel
- NapCat/AstrBot configuration changes require restart
- Testing completed and results need to be reported
- Critical errors cannot be auto-resolved and need manual intervention

### Notification Template
```
[计划助手通知]
{简短描述问题/操作}
{需要的操作}
{完成后请告知}
```

Example:
```
[计划助手通知]
WebUI 拆解功能已修复，需要重新加载插件。
请在 AstrBot 管理面板中找到"计划助手"，点击"更多" -> "重载插件"。
完成后请告知。
```
