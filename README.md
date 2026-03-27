# 计划助手（astrbot_plugin_planner）

一个用于 AstrBot 的计划任务插件，支持自然语言创建任务、补全缺失信息、定时提醒与任务管理。

## 功能

- 自然语言创建任务（任务名、时间、时长）
- 交互式补全：缺时间/缺时长时继续询问
- 支持"现在/立刻/马上"等即时时间表达
- 支持提醒时间配置（默认提前 10 分钟）
- 提供 LLM Tool：`create_planner_task`、`plan_with_ai`、`auto_plan_task`、`list_planner_tasks`、`complete_planner_task`、`cancel_planner_task`、`set_planner_config`、`planner_tool_contract`
- AI 规划：支持在"目标模糊、没想好什么时候做"的情况下自动拆解并建议时间（`/ai规划`、`plan_with_ai`）
- 习惯驱动规划：基于历史行为自动学习时长/时段/别名习惯，并用于智能推荐
- 即时反馈机制：用户可对规划结果给出反馈，影响后续推荐（`/计划反馈`）
- 事件追溯：持久化任务生命周期事件，支持习惯重建与数据审计
- 会话隔离：仅查看/操作当前会话创建的任务，避免跨会话误操作
- 学习系统支持自动开关：`/学习 自动开启`、`/学习 自动关闭`
- 习惯管理：支持查看、删除、重置学习数据（`/习惯 查看`、`/习惯 删除`、`/习惯 重建`、`/习惯 重置`）

## 使用方式

### 1) 命令模式（推荐）

#### 任务创建与规划
- `/计划 <描述>`：交互式创建任务
- `/ai规划 <模糊目标>`：让 AI 先给出可执行安排建议（不直接创建）
- `/计划反馈 <反馈内容>`：对 AI 规划结果给出即时反馈，影响后续推荐

#### 可视化图表
- `/图表 [今天/明天/本周/下周]`：主动查看可视化日程图（默认时间轴）
- `/图表 卡片 本周`：卡片样式
- `/图表 紧凑 今天`：紧凑列表样式
- 示例：`/计划 制作作品集`
- 示例：`/计划 今天下午3点写代码2小时`
- 示例：`/ai规划 这周把作品集和算法复习安排一下`
- 示例：`/图表 本周`

#### 习惯管理（别名：`/学习`）
- `/习惯` 或 `/习惯 查看`：查看当前学习到的习惯数据（时长、别名、时段模式）
- `/习惯 重建`：根据历史事件重新构建用户习惯档案（用于数据修复）
- `/习惯 最近事件`：查看最近的行为事件记录（创建/完成/取消/改期）
- `/习惯 删除 时长 <任务名>`：删除指定任务的时长学习记录
- `/习惯 删除 别名 <别名>`：删除别名学习记录
- `/习惯 删除 时段 <任务名>`：删除时段学习记录
- `/习惯 重置 全部`：清空所有学习数据（需二次确认）

#### 自动学习开关
- `/学习 自动开启`、`/学习 自动关闭`、`/学习 自动状态`：控制是否自动学习任务习惯

### 2) LLM Tool 模式

#### 任务管理
- `create_planner_task(description)`：单次创建（信息完整时直接创建）
- `list_planner_tasks(date_text="今天", include_done=false, limit=10)`：查看任务（支持今天/明天/本周/下周）
- `complete_planner_task(target)`：完成任务（target 可为编号或名称关键字，留空默认完成最近项）
- `cancel_planner_task(target)`：取消任务（target 可为编号、名称关键字、`all`）

#### AI 规划
- `auto_plan_task(user_text, auto_create=true)`：针对"帮我安排一下…"一类口语化需求的高优先级规划工具
- `plan_with_ai(intention, horizon="本周", max_tasks=5, auto_create=false)`：在信息不完整时让 AI 自动规划（可选直接创建）
- `planner_tool_contract`：返回工具选型与参数规范说明

#### 配置管理
- `set_planner_config(timeout_seconds, remind_before, habit_planning_enabled, habit_weight, suggestion_count, max_daily_minutes, learning_confidence_threshold)`：调整超时、提醒与习惯规划配置

## 配置项

见 `_conf_schema.json`：

### 基础配置
- `timeout_seconds`：创建任务时等待用户补全信息的超时时间（秒）
- `remind_before`：任务开始前多少分钟提醒
- `auto_plan_on_missing_time`：LLM工具缺少具体时间时是否自动补全可执行时间
- `avoid_past_time`：AI 规划结果是否自动避开过去时间
- `ai_default_duration_minutes`：AI 规划默认时长（分钟）

### 习惯规划配置
- `habit_planning_enabled`：是否启用习惯驱动自动规划（默认开启）
- `habit_weight`：习惯建议权重，0-1 之间，越高越倾向基于习惯推荐（默认 0.7）
- `suggestion_count`：每次规划最大建议任务数（默认 5）
- `max_daily_minutes`：每日习惯规划最大时长（默认 120 分钟）
- `learning_confidence_threshold`：习惯置信度阈值，低于此值减少习惯干预（默认 0.5）

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

## AI 规范文档

- 面向后续 AI/开发者的工具调用规范与需求记录：`AI_PROJECT_SPEC.md`
