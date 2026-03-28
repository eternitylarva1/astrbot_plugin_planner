#!/usr/bin/env python3
"""在本地快速导出日程图 HTML（可选导出 PNG）.

用法:
  PYTHONPATH=. python scripts/render_preview.py
  PYTHONPATH=. python scripts/render_preview.py --style card --png
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import List
import sys
import types

# 兼容本仓库“无顶层 __init__.py + 相对导入”结构，构建临时命名空间包。
ROOT = Path(__file__).resolve().parents[1]
PKG = "astrbot_plugin_planner"
if PKG not in sys.modules:
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PKG] = pkg
for sub in ("utils", "models"):
    fullname = f"{PKG}.{sub}"
    if fullname not in sys.modules:
        mod = types.ModuleType(fullname)
        mod.__path__ = [str(ROOT / sub)]
        sys.modules[fullname] = mod

from astrbot_plugin_planner.utils.visualizer import Visualizer


@dataclass
class _MockTask:
    name: str
    start_time: datetime
    duration_minutes: int
    status: str = "todo"


def _sample_tasks(target_date: date) -> List[_MockTask]:
    base = datetime.combine(target_date, time(hour=8, minute=30))
    return [
        _MockTask("晨间复盘", base, 40, "done"),
        _MockTask("需求评审会议", base + timedelta(hours=1), 60, "done"),
        _MockTask("核心功能开发", base + timedelta(hours=2, minutes=20), 150, "todo"),
        _MockTask("午间休息", base + timedelta(hours=5), 60, "todo"),
        _MockTask("接口联调", base + timedelta(hours=6, minutes=30), 90, "todo"),
        _MockTask("运动", base + timedelta(hours=9), 50, "todo"),
    ]


async def _export_png(html_path: Path, png_path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 2800})
        await page.goto(html_path.resolve().as_uri())
        await page.screenshot(path=str(png_path), full_page=True)
        await browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="导出可视化预览")
    parser.add_argument("--style", default="timeline", choices=["timeline", "card", "compact"])
    parser.add_argument("--png", action="store_true", help="额外导出 PNG（需要 playwright + chromium）")
    parser.add_argument("--out", default="artifacts/previews", help="输出目录")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    v = Visualizer()
    target = date.today()
    tasks = _sample_tasks(target)

    html = v.render_daily_schedule(tasks, target, style=args.style)
    html_path = out_dir / f"daily_{args.style}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"[ok] HTML 已生成: {html_path}")

    if args.png:
        png_path = out_dir / f"daily_{args.style}.png"
        try:
            asyncio.run(_export_png(html_path, png_path))
            print(f"[ok] PNG 已生成: {png_path}")
        except ModuleNotFoundError:
            print("[warn] 未安装 playwright，先执行: pip install playwright && playwright install chromium")
        except Exception as e:  # pragma: no cover - 诊断输出
            print(f"[warn] PNG 导出失败: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
