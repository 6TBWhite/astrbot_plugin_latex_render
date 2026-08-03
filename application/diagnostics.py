"""Safe runtime diagnostics and GIF animation probing."""

from __future__ import annotations

import asyncio
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from astrbot.api import logger
from astrbot.api.message_components import Image, Plain

from ..rendering.pipeline import RenderPipeline
from ..rendering.renderer import get_renderer_status
from ..template_system.manager import TemplateManager
from ..template_system.service import TemplateService


class DiagnosticsService:
    def __init__(
        self,
        pipeline: RenderPipeline,
        templates: TemplateService,
        plugin_dir: str,
        image_cache_dir: str,
    ):
        self.pipeline = pipeline
        self.templates = templates
        self.plugin_dir = Path(plugin_dir)
        self.image_cache_dir = Path(image_cache_dir)

    @staticmethod
    def has_probable_cjk_font() -> bool:
        if platform.system() == "Windows":
            font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            return any(
                (font_dir / filename).is_file()
                for filename in ("msyh.ttc", "msyh.ttf", "simsun.ttc", "simhei.ttf")
            )
        candidates = [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
            Path("/System/Library/Fonts/PingFang.ttc"),
        ]
        if any(path.is_file() for path in candidates):
            return True
        fc_list = shutil.which("fc-list")
        if not fc_list:
            return False
        try:
            result = subprocess.run(
                [fc_list, ":lang=zh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
            return bool(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return False

    def safe_status(self) -> dict:
        renderer = get_renderer_status()
        runtime = self.pipeline.snapshot()
        return {
            "browser_connected": bool(renderer.get("browser_connected", False)),
            "browser_launching": bool(renderer.get("browser_launching", False)),
            "mathjax_available": (
                self.plugin_dir / "assets" / "mathjax-tex-svg.js"
            ).is_file(),
            "cjk_font_available": self.has_probable_cjk_font(),
            "active_renders": runtime.active_renders,
            "queued_renders": runtime.queued_renders,
            "template_count": len(self.templates.available()),
            "custom_template_count": len(self.templates.manager.get_custom_templates()),
            "last_render_seconds": renderer.get("last_render_seconds", 0),
            "last_metrics": runtime.last_metrics,
            "last_error": runtime.last_error,
            "cooldown_seconds": runtime.cooldown_seconds,
        }

    def chat_status(self) -> str:
        renderer = get_renderer_status()
        runtime = self.pipeline.snapshot()
        cache_files, cache_bytes = self._cache_usage()
        browser_status = (
            "已连接" if renderer.get("browser_connected") else "未连接/待启动"
        )
        lines = [
            "🩺 LaTeX Render 状态",
            f"浏览器：{browser_status}",
            "MathJax："
            + (
                "可用"
                if (self.plugin_dir / "assets" / "mathjax-tex-svg.js").is_file()
                else "缺失"
            ),
            f"模板：{len(self.templates.available())} 个",
            f"中文字体：{'可用' if self.has_probable_cjk_font() else '未检测到'}",
            f"任务：运行 {runtime.active_renders} / 排队 {runtime.queued_renders}",
            f"缓存：{cache_files} 个文件 / {cache_bytes / 1024 / 1024:.1f} MiB",
        ]
        if runtime.last_metrics:
            metrics = runtime.last_metrics
            lines.append(
                "最近渲染："
                f"{metrics.get('duration_seconds', '?')}s，"
                f"{metrics.get('image_count', metrics.get('page_count', '?'))} 张，"
                f"模板 {metrics.get('template', '?')}"
            )
        if runtime.last_error:
            error = runtime.last_error
            lines.append(
                f"最后错误：{error.get('code', 'unknown')} - {error.get('message', '')}"
            )
        else:
            lines.append("最后错误：无")
        return "\n".join(lines)

    def _cache_usage(self) -> tuple[int, int]:
        count = 0
        size = 0
        try:
            for entry in os.scandir(self.image_cache_dir):
                if entry.is_file():
                    count += 1
                    size += entry.stat().st_size
        except OSError:
            pass
        return count, size

    async def gif_probe(self) -> list:
        """Return a user-facing component chain containing three sampled frames."""

        from playwright.async_api import async_playwright

        html = re.sub(r"</?render[^>]*>", "", TemplateManager.get_gif_test_content())
        self.image_cache_dir.mkdir(parents=True, exist_ok=True)
        paths = [
            self.image_cache_dir / f"probe_frame_{index}.png" for index in range(3)
        ]
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                context = await browser.new_context(
                    device_scale_factor=2,
                    viewport={"width": 600, "height": 800},
                )
                page = await context.new_page()
                await page.set_content(html, wait_until="networkidle")
                content_height = await page.evaluate("document.body.scrollHeight")
                await page.set_viewport_size(
                    {"width": 600, "height": max(content_height, 200)}
                )
                await asyncio.sleep(1.0)
                animated_count = await page.evaluate(
                    "document.querySelectorAll('.track').length"
                )
                animated_info = await page.evaluate(self._animation_probe_script())
                self._log_animation_info(animated_info)
                for index, path in enumerate(paths):
                    await page.screenshot(path=str(path), full_page=True)
                    logger.info(f"[探针] 已截取第 {index + 1} 帧")
                    if index < 2:
                        await asyncio.sleep(1.0)
            finally:
                await browser.close()
        self.pipeline.schedule_delete(*(str(path) for path in paths))
        return [
            Plain(
                f"🔍 探针结果：检测到 {animated_count} 个动画元素\n"
                "详细信息请查看控制台日志\n\n以下是间隔1秒的3帧截图："
            ),
            *(Image.fromFileSystem(str(path)) for path in paths),
        ]

    @staticmethod
    def _animation_probe_script() -> str:
        return """() => {
            const items = document.querySelectorAll('.track');
            return Array.from(items).map((el, i) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return {
                    index: i, text: el.textContent.substring(0, 20),
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    width: Math.round(rect.width), height: Math.round(rect.height),
                    visible: rect.width > 0 && rect.height > 0,
                    animation: style.animation,
                    animationPlayState: style.animationPlayState,
                    transform: style.transform, left: style.left,
                    opacity: style.opacity, display: style.display,
                };
            });
        }"""

    @staticmethod
    def _log_animation_info(items: list[dict]) -> None:
        logger.info(f"[探针] 动画元素数量: {len(items)}")
        for info in items:
            logger.info(
                f"[探针] 动画元素#{info['index']}: text='{info['text']}' "
                f"pos=({info['x']},{info['y']}) "
                f"size={info['width']}x{info['height']} visible={info['visible']} "
                f"animation='{info['animation']}' state='{info['animationPlayState']}' "
                f"transform='{info['transform']}' left='{info['left']}'"
            )
