# 计划助手（astrbot_plugin_planner）

一个用于 AstrBot 的计划任务插件，支持自然语言创建任务、补全缺失信息、定时提醒与任务管理。

## 功能

- 自然语言创建任务（任务名、时间、时长）
- 交互式补全：缺时间/缺时长时继续询问
- 支持“现在/立刻/马上”等即时时间表达
- 支持提醒时间配置（默认提前 10 分钟）
- 提供 LLM Tool：`create_planner_task`、`list_planner_tasks`、`complete_planner_task`、`cancel_planner_task`、`set_planner_config`
- 会话隔离：仅查看/操作当前会话创建的任务，避免跨会话误操作

## 使用方式

### 1) 命令模式（推荐）

- `/计划 <描述>`：交互式创建任务
- `/图表 [今天/明天/本周/下周]`：主动查看可视化日程图（默认时间轴）
- `/图表 卡片 本周`：卡片样式
- `/图表 紧凑 今天`：紧凑列表样式
- 示例：`/计划 制作作品集`
- 示例：`/计划 今天下午3点写代码2小时`
- 示例：`/图表 本周`

### 2) LLM Tool 模式

- `create_planner_task(description)`：单次创建（信息完整时直接创建）
- `list_planner_tasks(date_text="今天", include_done=false, limit=10)`：查看任务（支持今天/明天/本周/下周）
- `complete_planner_task(target)`：完成任务（target 可为编号或名称关键字，留空默认完成最近项）
- `cancel_planner_task(target)`：取消任务（target 可为编号、名称关键字、`all`）
- `set_planner_config(timeout_seconds, remind_before)`：调整超时与提醒配置

## 配置项

见 `_conf_schema.json`：

- `timeout_seconds`：创建任务时等待用户补全信息的超时时间（秒）
- `remind_before`：任务开始前多少分钟提醒

## 兼容性

- AstrBot: `>=4.16`
- 平台：`aiocqhttp`、`qq_official`

## 本地预览/截图调试（开发）

- 直接导出 HTML（不需要浏览器）：
  - `python scripts/render_preview.py`
  - 输出文件：`artifacts/previews/daily_timeline.html`
- 指定样式导出：
  - `python scripts/render_preview.py --style card`
  - `python scripts/render_preview.py --style compact`
- 如果你还想导出 PNG（用于“截图”效果）：
  1. 安装依赖：`pip install playwright`
  2. 安装浏览器：`playwright install chromium`
  3. 执行：`python scripts/render_preview.py --style timeline --png`

## 仓库

- https://github.com/eternitylarva1/astrbot_plugin_planner
