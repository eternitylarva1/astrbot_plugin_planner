# 开发说明文档 - astrbot_plugin_planner

## 项目概述

AstrBot 插件：智能计划助手。支持自然语言创建任务、定时提醒、可视化日程。

## 目录结构

```
astrbot_plugin_planner/
├── main.py                  # 插件入口（命令、LLM工具、事件处理）
├── utils/
│   └── time_parser.py       # 时间/时长解析核心逻辑
├── models/
│   └── task.py              # Task 数据模型（dataclass）
├── services/
│   ├── storage_service.py   # JSON 文件存储服务
│   ├── task_service.py      # 任务 CRUD 操作
│   ├── reminder_service.py  # APScheduler 定时提醒
│   └── learning_service.py  # 用户偏好学习
├── _conf_schema.json        # WebUI 可视化配置
├── requirements.txt         # 依赖
└── metadata.yaml            # 插件元数据
```

## 核心架构

### 两个入口点

| 入口 | 用途 | 模式 |
|------|------|------|
| `/计划` 命令 | 交互式多轮对话 | 有状态（_pending_tasks） |
| `create_planner_task` LLM 工具 | 单次创建 | 无状态（单轮） |

**关键设计决策**：LLM 工具**不创建 pending task**，只做单次解析/创建。多轮交互只走 `/计划` 命令。这是为了防止 AI 在任何消息上误触创建 pending task → 导致幽灵超时。

### 状态机（/计划 命令）

```
用户发送 /计划 <描述>
  ├── 有时间 + 有时长 → 直接创建任务
  ├── 缺时长 → pending step="awaiting_duration" → 等用户回复
  └── 缺时间 → pending step="awaiting_time" → 等用户回复

用户回复（on_pending_message）
  ├── 超时 → 清除 pending → 发送超时消息
  ├── step="awaiting_duration" → 解析时长
  │   ├── 有时间 → 创建任务
  │   └── 缺时间 → 改为 awaiting_time
  └── step="awaiting_time" → 解析时间
      ├── 有时间 + 有时长 → 创建任务
      └── 缺时长 → 改为 awaiting_duration
```

## 时间解析 (time_parser.py)

### parse_duration(text) -> Optional[int]

解析时长，返回**分钟数**（int）或 None。

**返回类型**：
- `int`：成功解析的分钟数
- `None`：无法解析

**支持的表达**：
```
1小时 → 60
30分钟 → 30
1.5小时 → 90
1.5 小时 → 90
2周 → 20160
1天 → 1440
```

**⚠️ 重要：返回类型差异**
- 插件版：`Optional[int]`（None 表示失败）
- 测试版：`tuple[int, bool]`（-1 表示失败，bool 表示模糊）
- **不能混用！**

### parse_datetime(text, reference_date) -> Optional[datetime]

解析日期时间，返回 datetime 或 None。

**支持的表达**：
```
今天、明天、后天、大后天
周一、下周三、本周五
下午3点、15:30、晚上8点、凌晨3点
现在、立刻、马上、立即、此时、此刻  → 返回当前时刻
```

**⚠️ 关键修复（"现在"检测）**：
```python
# 优先检测立即时间词
immediate_kws = ["现在", "立刻", "马上", "立即", "此时", "此刻"]
for kw in immediate_kws:
    if kw in text_lower:
        return datetime.combine(reference_date, datetime.now().time())
```

## 已知问题和修复

### Bug 1：LLM 工具误触创建 pending task

**症状**：用户没调用任何命令，但收到"抱歉，上次的问题已超时"。

**原因**：`create_planner_task` LLM 工具在信息不完整时会创建 `_pending_tasks`。由于 LLM 工具可被 AI 在任何消息上触发，用户随便说句话就可能创建 pending task → 2分钟后超时。

**修复**：LLM 工具**不创建 pending task**。信息不完整时返回提示文本，由用户决定是否重新调用或使用 `/计划` 命令。

### Bug 2：parse_duration 返回类型不匹配

**症状**："1小时"被误判为"没理解这个时长"。

**原因**：代码检查 `if duration == -1`，但插件版 `parse_duration` 返回 `Optional[int]`（None 表示失败，60 表示成功），永远不会返回 -1。

**修复**：改为检查模糊词：
```python
fuzzy_keywords = {"大概", "左右", "估计", "差不多", "些许"}
has_fuzzy = any(kw in user_input for kw in fuzzy_keywords)
if has_fuzzy:
    # 模糊处理
```

### Bug 3："现在"不被识别

**症状**：用户说"现在做作业"，时间被忽略。

**修复**：在 `parse_datetime` 开头添加立即时间词检测：
```python
immediate_kws = ["现在", "立刻", "马上", "立即", "此时", "此刻"]
```

### Bug 4：Windows datetime.now() 精度问题

**症状**：`time.perf_counter()` 更稳定，连续调用不会出错。

**修复**：pending task 的超时检查改用 `time.perf_counter()`：
```python
pending["pending_at"] = time.perf_counter()
elapsed = time.perf_counter() - pending["pending_at"]
```

## 配置说明 (_conf_schema.json)

```json
{
  "timeout_seconds": {
    "description": "创建任务时等待用户回复的超时时间（秒）",
    "type": "int",
    "default": 120
  },
  "remind_before": {
    "description": "任务开始前多少分钟提醒",
    "type": "int",
    "default": 10
  }
}
```

## 测试 (test_planner_logic.py)

独立测试文件，不依赖 AstrBot 框架。

### 运行方式

```bash
cd C:\Users\gaoming\Downloads\opencode
python test_planner_logic.py
```

### 测试覆盖（85 个用例）

```
【时长解析】parse_duration
  ✓ 1小时 → 60
  ✓ 30分钟 → 30
  ✓ 1.5小时 → 90
  ✓ 大概1小时 → (60, True)
  ✓ 估计30分钟 → (30, True)
  ✓ 洗个澡 → (-1, False)
  ✓ 2周 → 20160

【日期时间解析】parse_datetime
  ✓ 今天下午3点 → hour=15
  ✓ 明天上午9点 → hour=9
  ✓ 下周三
  ✓ 15:30 → hour=15 min=30
  ✓ 洗个澡 → None
  ✓ 下午3点 → hour=15
  ✓ 晚上8点 → hour=20
  ✓ 上午9:30 → hour=9 min=30
  ✓ 现在/立刻/马上 → 返回当前时间

【核心状态机】Planner
  ✓ 完整任务直接创建
  ✓ 缺时长 → pending → 回复时长 → 创建
  ✓ 缺时间 → pending → 回复时间 → 创建
  ✓ 缺两者 → 先问时长 → 再问时间 → 创建
  ✓ 模糊时长处理
  ✓ 超时取消
  ✓ 取消任务
  ✓ 重复任务
```

## LLM 工具说明

### create_planner_task(description: str) -> str

创建计划任务。一次性完成，**不创建 pending task**。

**参数**：
- `description`：任务描述，必须包含名称、时间、时长

**返回**：
- 信息完整 → 返回创建成功消息
- 缺信息 → 返回提示文本，告知用户补充

**示例**：
```
"明天下午3点写代码2小时" → 创建成功
"现在做毕业设计4小时" → 创建成功
"做作业" → 返回提示，需要补充时间和时长
```

### set_planner_config(timeout_seconds?, remind_before?) -> str

设置配置参数。AI 可调用。

## 数据存储

所有数据存储在 `data/plugin_data/astrbot_plugin_planner/` 目录：

| 文件 | 用途 |
|------|------|
| tasks.json | 任务数据 |
| learning.json | 用户偏好学习数据 |
| recurring.json | 循环任务 |
| goals.json | 目标数据 |
| history.json | 历史记录 |

## 常见问题

### Q: 为什么有时候 AI 自动创建了 pending task？
A: 这是 LLM 工具误触的问题。修复后，`create_planner_task` 不再创建 pending task。

### Q: "1小时" 为什么有时不被识别？
A: 检查 `time_parser.py` 的版本。插件版应该返回 `Optional[int]`，不是 `tuple`。

### Q: "现在" 为什么不能正确识别时间？
A: 确保 `time_parser.py` 中有立即时间词检测代码。

### Q: 测试通过但插件运行有问题？
A: 检查两个文件的版本是否同步（源文件 vs 安装目录）。

## 部署注意事项

1. 源文件位置：`C:\Users\gaoming\Downloads\opencode\astrbot_plugin_planner\`
2. 安装目录：`C:\Users\gaoming\.astrbot_launcher\instances\d155e712-eb81-41f9-8183-42fb44bc9e3f\core\data\plugins\astrbot_plugin_planner\`
3. 修改后需要同步（复制）到安装目录
4. 重启 AstrBot 后生效
5. LSP 错误（astrbot.api imports 无法解析）是正常的，不需要处理

## 版本历史

- v0.1.0：初始版本
- v1.0.0：修复 LLM 工具 pending task 问题、parse_duration 返回类型不匹配、"现在"识别、超时消息硬编码
