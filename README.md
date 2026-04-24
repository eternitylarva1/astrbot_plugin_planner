# 计划助手（astrbot_plugin_planner）

基于 [Schedule App](https://github.com/eternitylarva1/schedule_app) 后端的 AstrBot 插件，通过自然语言创建日程、AI 任务拆解与目标规划。

## 功能

- 自然语言创建日程（自动解析时间、时长、分类）
- AI 任务拆解（`/拆解`）
- AI 模糊目标规划（`/ai规划`）
- 日程查看（今日/明天/本周）
- 可视化图表（截图）
- 任务完成/取消管理

## 依赖

- **Schedule App 后端**：必须运行在 `http://localhost:8080`
- AstrBot >= 4.16

## 快速开始

1. 安装 [Schedule App](https://github.com/eternitylarva1/schedule_app) 后端并启动
2. 配置插件 `schedule_api_base` 为后端地址（默认 `http://localhost:8080`）
3. 重载插件即可使用

## 指令

| 指令 | 说明 |
|------|------|
| `/计划 <描述>` | 创建日程，如 `/计划 明天下午3点开会` |
| `/日程 [今日/明天/本周]` | 查看日程列表 |
| `/图表 [今天/本周]` | 查看可视化图表（截图） |
| `/完成 <编号/名称>` | 完成任务 |
| `/取消 <编号/名称/-1>` | 取消日程，-1 删除今天全部 |
| `/待办` | 查看待办列表 |
| `/ai规划 <目标>` | AI 模糊目标规划 |
| `/拆解 <任务>` | 任务拆解 |
| `/统计 [今天/本周]` | 查看完成率统计 |
| `/设置` | 查看当前设置 |
| `/帮助` | 显示帮助 |

**别名**：部分指令支持别名，如 `/任务` 等同于 `/日程`，`/done` 等同于 `/完成`。

## 配置

在插件设置中配置：

- `schedule_api_base`：后端 API 地址（默认 `http://localhost:8080`）
- `frontend_url`：前端地址，用于截图（默认 `http://localhost:8080`）
- `enable_screenshot`：是否启用截图功能

## 架构

```
AstrBot 插件 (main.py)
       │
       ▼ API
Schedule App 后端 (aiohttp + SQLite)
```

所有日程数据存储在 Schedule App 的 SQLite 数据库中。

## 仓库

https://github.com/eternitylarva1/astrbot_plugin_planner