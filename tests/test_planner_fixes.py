"""
测试计划助手插件的三个问题修复
不依赖 AstrBot 框架的独立测试程序
"""

import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


_DATA_ROOT = Path(tempfile.mkdtemp(prefix="planner_test_data_"))


def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    sys.modules["astrbot"] = astrbot

    api = types.ModuleType("astrbot.api")
    api.logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
    api.AstrBotConfig = dict
    sys.modules["astrbot.api"] = api

    msg = types.ModuleType("astrbot.api.message_components")
    sys.modules["astrbot.api.message_components"] = msg

    event = types.ModuleType("astrbot.api.event")

    class _Filter:
        class EventMessageType:
            PRIVATE_MESSAGE = "private"

        def command(self, *args, **kwargs):
            return lambda func: func

        def llm_tool(self, *args, **kwargs):
            return lambda func: func

        def event_message_type(self, *args, **kwargs):
            return lambda func: func

    event.filter = _Filter()
    event.AstrMessageEvent = object
    event.MessageEventResult = object
    sys.modules["astrbot.api.event"] = event

    star = types.ModuleType("astrbot.api.star")

    class _Star:
        def __init__(self, context):
            self.context = context

    star.Context = object
    star.Star = _Star
    star.register = lambda *a, **k: (lambda cls: cls)
    sys.modules["astrbot.api.star"] = star

    core = types.ModuleType("astrbot.core")
    sys.modules["astrbot.core"] = core

    core_utils = types.ModuleType("astrbot.core.utils")
    sys.modules["astrbot.core.utils"] = core_utils

    sw = types.ModuleType("astrbot.core.utils.session_waiter")
    sw.session_waiter = lambda *a, **k: (lambda func: func)
    sw.SessionController = object
    sys.modules["astrbot.core.utils.session_waiter"] = sw

    path_mod = types.ModuleType("astrbot.core.utils.astrbot_path")
    path_mod.get_astrbot_data_path = lambda: _DATA_ROOT
    sys.modules["astrbot.core.utils.astrbot_path"] = path_mod


def _load_plugin_module():
    repo_root = Path(__file__).resolve().parents[1]
    package_name = "astrbot_plugin_planner"
    if package_name not in sys.modules:
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [str(repo_root)]
        sys.modules[package_name] = pkg

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.main", repo_root / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeConfig(dict):
    async def save_config(self):
        return None


class _FakeEvent:
    def __init__(self, origin: str = "test-session"):
        self.unified_msg_origin = origin
        self.message_str = ""


class TestPlannerFixes(unittest.IsolatedAsyncioTestCase):
    """测试计划助手插件的三个问题修复"""
    
    @classmethod
    def setUpClass(cls):
        _install_astrbot_stubs()
        cls.main_module = _load_plugin_module()
        cls.PlannerPlugin = cls.main_module.PlannerPlugin

    async def asyncSetUp(self):
        global _DATA_ROOT
        self.work_dir = Path(tempfile.mkdtemp(prefix="planner_case_", dir=_DATA_ROOT))
        _DATA_ROOT = self.work_dir
        self.plugin = self.PlannerPlugin(
            context=types.SimpleNamespace(),
            config=_FakeConfig({
                "timeout_seconds": 120,
                "remind_before": 10,
                "auto_plan_on_missing_time": True,
                "avoid_past_time": True,
                "ai_default_duration_minutes": 45,
                "habit_planning_enabled": False,
                "habit_weight": 0.7,
                "suggestion_count": 3,
                "max_daily_minutes": 360,
                "learning_confidence_threshold": 0.35,
            })
        )
    
    # ========== 问题一：待办列表与任务列表不一致 ==========
    
    async def test_issue1_list_and_resolve_consistency(self):
        """测试问题一：list_planner_tasks 和 _resolve_pending_task 使用相同的任务列表"""
        event = _FakeEvent("test-session")
        
        # 创建今天的任务
        await self.plugin.create_planner_task(
            event=event,
            description="今天上午9点写代码1小时"
        )
        await self.plugin.create_planner_task(
            event=event,
            description="今天下午2点开会1小时"
        )
        
        # 创建明天的任务
        await self.plugin.create_planner_task(
            event=event,
            description="明天上午10点复习英语1小时"
        )
        
        # 测试 list_planner_tasks("今天") 只返回今天的任务
        result = await self.plugin.list_planner_tasks(
            event=event,
            date_text="今天",
            include_done=False,
            limit=10
        )
        self.assertIn("写代码", result)
        self.assertIn("开会", result)
        self.assertNotIn("复习英语", result)
        
        # 测试 _resolve_pending_task 使用 date_text 参数
        task = await self.plugin._resolve_pending_task(
            session_origin="test-session",
            target="1",
            date_text="今天"
        )
        self.assertIsNotNone(task)
        self.assertEqual(task.name, "写代码")
        
        task = await self.plugin._resolve_pending_task(
            session_origin="test-session",
            target="2",
            date_text="今天"
        )
        self.assertIsNotNone(task)
        self.assertEqual(task.name, "开会")
        
        # 测试使用 date_text="明天"
        task = await self.plugin._resolve_pending_task(
            session_origin="test-session",
            target="1",
            date_text="明天"
        )
        self.assertIsNotNone(task)
        self.assertEqual(task.name, "复习英语")
    
    # ========== 问题二：批量创建任务时时间识别问题 ==========
    
    async def test_issue2_sequential_task_planning(self):
        """测试问题二：批量任务之间有时间关联"""
        event = _FakeEvent("test-session")
        
        # 使用 plan_with_ai 批量创建任务
        result = await self.plugin.plan_with_ai(
            event=event,
            intention="明天下午3点开会，然后写代码，最后复习英语",
            horizon="明天",
            max_tasks=3,
            auto_create=True
        )
        
        self.assertIn("已根据 AI 规划创建", result)
        
        # 获取明天的任务
        from datetime import date
        tomorrow = date.today() + timedelta(days=1)
        tasks = await self.plugin.task_service.get_tasks_by_date(tomorrow)
        tasks = [t for t in tasks if t.session_origin == "test-session"]
        
        # 验证任务按顺序排列
        self.assertGreaterEqual(len(tasks), 2)
        
        # 验证后续任务的时间在前一个任务之后
        for i in range(len(tasks) - 1):
            current_end = tasks[i].start_time + timedelta(minutes=tasks[i].duration_minutes)
            next_start = tasks[i + 1].start_time
            self.assertGreaterEqual(
                next_start, current_end,
                f"任务 {i+1} 的结束时间应该在任务 {i+2} 的开始时间之前或相同"
            )
    
    # ========== 问题三：批量处理功能缺失 ==========
    
    def test_issue3_parse_batch_targets(self):
        """测试问题三：_parse_batch_targets 解析批量编号"""
        # 测试单个编号
        result = self.PlannerPlugin._parse_batch_targets("1")
        self.assertEqual(result, [1])
        
        # 测试逗号分隔
        result = self.PlannerPlugin._parse_batch_targets("1,2,3")
        self.assertEqual(result, [1, 2, 3])
        
        # 测试范围
        result = self.PlannerPlugin._parse_batch_targets("1-3")
        self.assertEqual(result, [1, 2, 3])
        
        # 测试混合格式
        result = self.PlannerPlugin._parse_batch_targets("1,3-5")
        self.assertEqual(result, [1, 3, 4, 5])
        
        # 测试空字符串
        result = self.PlannerPlugin._parse_batch_targets("")
        self.assertEqual(result, [])
        
        # 测试无效输入
        result = self.PlannerPlugin._parse_batch_targets("abc")
        self.assertEqual(result, [])
        
        # 测试反向范围
        result = self.PlannerPlugin._parse_batch_targets("5-3")
        self.assertEqual(result, [3, 4, 5])
        
        # 测试重复编号
        result = self.PlannerPlugin._parse_batch_targets("1,2,2,3")
        self.assertEqual(result, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
