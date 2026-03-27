# 计划助手（astrbot_plugin_planner）

一个用于 AstrBot 的计划任务插件，支持自然语言创建任务、补全缺失信息、定时提醒与任务管理。

## 功能

- 自然语言创建任务（任务名、时间、时长）
- 交互式补全：缺时间/缺时长时继续询问
- 支持“现在/立刻/马上”等即时时间表达
- 支持提醒时间配置（默认提前 10 分钟）
- 提供 LLM Tool：`create_planner_task`、`list_planner_tasks`、`complete_planner_task`、`cancel_planner_task`、`set_planner_config`
- 新增 AI 规划：支持在“目标模糊、没想好什么时候做”的情况下自动拆解并建议时间（`/ai规划`、`plan_with_ai`）
- 会话隔离：仅查看/操作当前会话创建的任务，避免跨会话误操作
- 学习系统支持自动开关：`/学习 自动开启`、`/学习 自动关闭`

## 使用方式

### 1) 命令模式（推荐）

- `/计划 <描述>`：交互式创建任务
- `/ai规划 <模糊目标>`：让 AI 先给出可执行安排建议（不直接创建）
- `/图表 [今天/明天/本周/下周]`：主动查看可视化日程图（默认时间轴）
- `/图表 卡片 本周`：卡片样式
- `/图表 紧凑 今天`：紧凑列表样式
- 示例：`/计划 制作作品集`
- 示例：`/计划 今天下午3点写代码2小时`
- 示例：`/ai规划 这周把作品集和算法复习安排一下`
- 示例：`/图表 本周`

### 2) LLM Tool 模式

- `create_planner_task(description)`：单次创建（信息完整时直接创建）
- `list_planner_tasks(date_text="今天", include_done=false, limit=10)`：查看任务（支持今天/明天/本周/下周）
- `complete_planner_task(target)`：完成任务（target 可为编号或名称关键字，留空默认完成最近项）
- `cancel_planner_task(target)`：取消任务（target 可为编号、名称关键字、`all`）
- `set_planner_config(timeout_seconds, remind_before)`：调整超时与提醒配置
- `plan_with_ai(intention, horizon="本周", max_tasks=5, auto_create=false)`：在信息不完整时让 AI 自动规划（可选直接创建）

## 配置项

见 `_conf_schema.json`：

- `timeout_seconds`：创建任务时等待用户补全信息的超时时间（秒）
- `remind_before`：任务开始前多少分钟提醒

## 兼容性

- AstrBot: `>=4.16`
- 平台：`aiocqhttp`、`qq_official`

## 仓库

- https://github.com/eternitylarva1/astrbot_plugin_planner
