# AI Project Spec for `astrbot_plugin_planner`

> 这份文档给后续接手的 AI（或开发者）看，目标是让“LLM 正确填工具参数并稳定执行”，而不是在插件里做复杂自然语言硬解析。

## 1. 用户核心诉求（必须满足）

1. 用户经常只给模糊目标（例如“这周安排一下一个小时做视频”）。
2. 希望由 LLM 主导规划，不要求用户先写出完整结构化计划。
3. 规划结果不能出现过去时间。
4. 工具参数必须明确，便于不同 AI 稳定调用。
5. 要有可配置项控制自动行为。

## 2. 工具调用策略（给 LLM）

### A) `create_planner_task`（明确任务时使用）

当用户已经给出明确的任务要素（任务名/时间/时长）时使用。

推荐参数：

```json
{
  "task_name": "做视频",
  "task_time": "2026-03-28 20:00",
  "duration_minutes": 60,
  "repeat": null
}
```

规则：
- `duration_minutes` 优先级高于 `duration`。
- 不要把完整闲聊句子塞到 `task_name`。

### B) `plan_with_ai` / `auto_plan_task`（模糊目标时使用）

当用户说“帮我安排/规划一下……”且参数不全时，优先用这两个工具。

推荐参数：

```json
{
  "intention": "这周安排一下一个小时做视频",
  "horizon": "本周",
  "max_tasks": 3,
  "auto_create": true
}
```

### C) `set_planner_config`（行为调优）

可调关键参数：
- `auto_plan_on_missing_time`
- `avoid_past_time`
- `ai_default_duration_minutes`

## 3. 当前插件约束

- 默认应避免过去时间（`avoid_past_time=true`）。
- 在缺少时间时，允许自动补全（`auto_plan_on_missing_time=true`）。
- 当 LLM 参数缺失时，插件应返回“结构化参数模板”提示，促使二次调用而非静默失败。

## 4. 回归测试建议（每次改动都跑）

1. 明确创建：
   - “明天晚上8点做视频1小时” → 应直接创建。
2. 模糊规划：
   - “这周帮我安排一下做视频” → 应进入 `plan_with_ai/auto_plan_task`。
3. 过去时间保护：
   - 在晚间请求“今天上午做视频”时，不应返回过去时间。
4. 口语时长：
   - “一个小时/半小时/一个钟头” 应被识别。
