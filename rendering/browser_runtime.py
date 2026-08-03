"""Playwright browser dependency and lifecycle management."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from astrbot.api import logger

from .renderer import close_browser, init_browser


class BrowserRuntime:
    def __init__(self, data_dir: str):
        self.browsers_dir = Path(data_dir) / "playwright_browsers"

    def configure(self) -> None:
        self.browsers_dir.mkdir(parents=True, exist_ok=True)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self.browsers_dir)
        logger.info(f"HTML渲染插件: Playwright 浏览器路径 → {self.browsers_dir}")

    def expected_headless_shell_dir(self) -> Path:
        import playwright

        manifest_path = (
            Path(playwright.__file__).resolve().parent
            / "driver"
            / "package"
            / "browsers.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        browser = next(
            item
            for item in manifest.get("browsers", [])
            if item.get("name") == "chromium-headless-shell"
        )
        return self.browsers_dir / f"chromium_headless_shell-{browser['revision']}"

    async def ensure_installed(self) -> None:
        expected = None
        try:
            expected = self.expected_headless_shell_dir()
        except Exception as exc:
            logger.warning(
                f"HTML渲染插件: 无法检查 Playwright 浏览器版本，将重新安装: {exc}"
            )
        executable_names = {"chrome-headless-shell", "chrome-headless-shell.exe"}
        if (
            expected
            and expected.is_dir()
            and any(
                path.is_file() and path.name in executable_names
                for path in expected.rglob("*")
            )
        ):
            logger.info(
                "HTML渲染插件: Playwright Chromium headless shell 已存在，跳过安装"
            )
            return
        if expected:
            logger.info(
                f"HTML渲染插件: 当前 Playwright 所需浏览器不存在，将安装: {expected}"
            )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium-headless-shell",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            details = (
                stderr.decode("utf-8", errors="ignore").strip()
                or stdout.decode("utf-8", errors="ignore").strip()
                or f"退出码 {process.returncode}"
            )
            raise RuntimeError(
                "无法安装 Playwright Chromium headless shell；请按 README 的“手动安装项”处理后重载插件"
            ) from RuntimeError(details)

    async def start(self) -> None:
        await self.ensure_installed()
        await init_browser()

    async def stop(self) -> None:
        await close_browser()
