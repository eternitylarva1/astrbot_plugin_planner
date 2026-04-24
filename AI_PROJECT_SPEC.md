# AI Project Spec

> 本文档记录工具调用规范（已过时，仅作历史参考）

## v2.0.0 重构说明

v2.0 起，插件改为基于 Schedule App 后端 API 的架构，不再内置 LLM 工具。所有功能通过 API 调用 Schedule App 的 `/api/llm/*` 端点实现。

## 历史工具调用（已废弃）

以下工具在 v1.x 版本使用，v2.0 已移除：

- `create_planner_task` → 使用 `/计划` 指令或 `POST /api/llm/create`
- `plan_with_ai` → 使用 `/ai规划` 指令或 `POST /api/llm/breakdown`
- `auto_plan_task` → 使用 `/ai规划` 指令
- `list_planner_tasks` → 使用 `/日程` 或 `GET /api/events`
- `complete_planner_task` → 使用 `/完成` 或 `PUT /api/events/{id}/complete`
- `cancel_planner_task` → 使用 `/取消` 或 `DELETE /api/events/{id}`
- `set_planner_config` → 通过 Schedule App 设置页面配置
- `breakdown_task` → 使用 `/拆解` 或 `POST /api/llm/breakdown`