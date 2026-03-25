# 计划助手（astrbot_plugin_planner）

一个用于 AstrBot 的计划任务插件，支持自然语言创建任务、补全缺失信息、定时提醒。

## 功能

- 自然语言创建任务（任务名、时间、时长）
- 交互式补全：缺时间/缺时长时继续询问
- 支持“现在/立刻/马上”等即时时间表达
- 支持提醒时间配置（默认提前 10 分钟）
- 提供 LLM Tool：`create_planner_task`、`set_planner_config`

## 使用方式

### 1) 命令模式（推荐）

- `/计划 <描述>`：交互式创建任务
- 示例：`/计划 制作作品集`
- 示例：`/计划 今天下午3点写代码2小时`

### 2) LLM Tool 模式

- `create_planner_task(description)`：单次创建（信息完整时直接创建）
- `set_planner_config(timeout_seconds, remind_before)`：调整超时与提醒配置

## 配置项

见 `_conf_schema.json`：

- `timeout_seconds`：创建任务时等待用户补全信息的超时时间（秒）
- `remind_before`：任务开始前多少分钟提醒

## 兼容性

- AstrBot: `>=4.16`
- 平台：`aiocqhttp`、`qq_official`

## 仓库

- https://github.com/eternitylarva1/astrbot_plugin_planner
