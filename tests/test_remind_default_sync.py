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


class TestRemindDefaultSync(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        _install_astrbot_stubs()
        cls.main_module = _load_plugin_module()

    async def asyncSetUp(self):
        global _DATA_ROOT
        self.work_dir = Path(tempfile.mkdtemp(prefix="planner_case_", dir=_DATA_ROOT))
        _DATA_ROOT = self.work_dir
        self.plugin = self.main_module.PlannerPlugin(
            context=types.SimpleNamespace(),
            config=_FakeConfig({"remind_before": 25}),
        )

    async def test_first_install_syncs_config_default_to_learning(self):
        event = _FakeEvent()
        task_time = datetime.now() + timedelta(days=1)
        prep = await self.plugin._prepare_task_creation(event, "写代码", task_time, 60)

        self.assertTrue(prep["ok"])
        self.assertEqual(prep["task"].remind_before, 25)

        learning = await self.plugin.storage.get_learning_data()
        self.assertEqual(learning.get("remind_preferences", {}).get("default"), 25)

    async def test_existing_learning_default_is_preserved(self):
        await self.plugin.storage.save_learning_data({"remind_preferences": {"default": 7}})
        event = _FakeEvent()
        task_time = datetime.now() + timedelta(days=1)
        prep = await self.plugin._prepare_task_creation(event, "开会", task_time, 30)

        self.assertTrue(prep["ok"])
        self.assertEqual(prep["task"].remind_before, 7)

    async def test_set_config_updates_future_task_remind_before(self):
        event = _FakeEvent()
        msg = await self.plugin.set_planner_config(event, remind_before=33)
        self.assertIn("提前 33 分钟提醒", msg)

        task_time = datetime.now() + timedelta(days=2)
        prep = await self.plugin._prepare_task_creation(event, "复习英语", task_time, 45)

        self.assertTrue(prep["ok"])
        self.assertEqual(prep["task"].remind_before, 33)

        learning = await self.plugin.storage.get_learning_data()
        self.assertEqual(learning.get("remind_preferences", {}).get("default"), 33)
