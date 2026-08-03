"""High-level rendering pipeline and resource controls."""

from __future__ import annotations

import asyncio
import os
import time
import uuid

from astrbot.api import logger
from astrbot.api.message_components import Image

from .config import RenderConfig, normalize_layout
from .document import HtmlDocumentBuilder
from .models import (
    BrowserRenderResult,
    RenderFailure,
    RenderResult,
    RenderRuntimeSnapshot,
)
from .renderer import RenderOptions, html_to_image_playwright


class RenderPipeline:
    def __init__(
        self,
        config: RenderConfig,
        documents: HtmlDocumentBuilder,
        image_cache_dir: str,
    ):
        self.config = config
        self.documents = documents
        self.image_cache_dir = image_cache_dir
        self.gif_duration = float(config.get("gif_duration", 3.0))
        self.gif_fps = int(config.get("gif_fps", 15))
        self.active_renders = 0
        self.queued_renders = 0
        self._semaphore_state: tuple[object, int, asyncio.Semaphore] | None = None
        self.last_metrics: dict = {}
        self.last_error: dict = {}
        self.browser_failure_count = 0
        self.browser_cooldown_until = 0.0

    async def render(
        self,
        content: str,
        specified_template: str | None,
        user_id: str | None = None,
        is_gif: bool = False,
        *,
        layout: str | None = None,
        style_overrides: dict | None = None,
        template_html_override: str | None = None,
    ) -> RenderResult:
        if not content or not content.strip():
            raise RenderFailure("invalid_content", "内容不能为空")
        limit = self.config.integer("max_input_chars", 50_000, 100, 500_000)
        if len(content) > limit:
            raise RenderFailure(
                "resource_limit",
                f"内容长度为 {len(content)} 字符，超过上限 {limit} 字符",
            )
        timeout = self.config.number("render_timeout_seconds", 30.0, 5.0, 180.0)
        semaphore = self._semaphore()
        max_queue = self.config.integer("max_queue_size", 8, 0, 100)
        if semaphore.locked() and self.queued_renders >= max_queue:
            raise RenderFailure("queue_full", "渲染队列已满，请稍后重试")
        self.queued_renders += 1
        try:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise RenderFailure("timeout", "等待渲染队列超时") from exc
        finally:
            self.queued_renders -= 1
        self.active_renders += 1
        try:
            return await asyncio.wait_for(
                self._render_inner(
                    content,
                    specified_template,
                    user_id,
                    is_gif,
                    layout=layout,
                    style_overrides=style_overrides,
                    template_html_override=template_html_override,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            self._record_error("timeout", "渲染执行超时")
            raise RenderFailure(
                "timeout", "渲染执行超时，请缩短内容或稍后重试"
            ) from exc
        except RenderFailure as exc:
            self._record_error(exc.code, exc.message)
            raise
        except Exception as exc:
            self._record_error("internal_error", str(exc))
            logger.exception(f"渲染过程异常: {exc}")
            raise RenderFailure("internal_error", "渲染发生内部错误") from exc
        finally:
            self.active_renders -= 1
            semaphore.release()

    async def render_for_layout(
        self,
        content: str,
        template: str | None,
        user_id: str | None,
        is_gif: bool,
        layout: str,
    ) -> RenderResult:
        if layout == "auto":
            return await self.render(content, template, user_id, is_gif)
        return await self.render(content, template, user_id, is_gif, layout=layout)

    async def _render_inner(
        self,
        content: str,
        specified_template: str | None,
        user_id: str | None,
        is_gif: bool,
        *,
        layout: str | None,
        style_overrides: dict | None,
        template_html_override: str | None,
    ) -> RenderResult:
        if time.monotonic() < self.browser_cooldown_until:
            remaining = int(self.browser_cooldown_until - time.monotonic()) + 1
            raise RenderFailure(
                "browser_cooldown", f"浏览器连续失败，正在冷却，请 {remaining} 秒后重试"
            )
        template_name, metadata, html, trusted = self.documents.build(
            content,
            specified_template,
            user_id,
            style_overrides,
            template_html_override,
        )
        logger.debug(f"HTML渲染: 使用模板 {template_name}, GIF模式: {is_gif}")
        options = self.build_options(
            html, metadata, is_gif, layout, style_overrides, trusted
        )
        normalized = await self.run_browser(options)
        return self._finalize(normalized, template_name, options.layout)

    def build_options(
        self,
        html: str,
        metadata: dict,
        is_gif: bool,
        layout: str | None,
        style_overrides: dict | None,
        trusted: bool,
    ) -> RenderOptions:
        os.makedirs(self.image_cache_dir, exist_ok=True)
        output = os.path.join(
            self.image_cache_dir, f"render_{uuid.uuid4().hex[:12]}.jpg"
        )
        width = self.config.integer("render_width", 600, 320, 1600)
        preferred_width = metadata.get("preferred_width")
        if isinstance(metadata.get("fixed_page"), dict) and isinstance(
            preferred_width, (int, float)
        ):
            width = max(320, min(int(preferred_width), 1600))
        scale = self.config.integer("render_scale", 2, 1, 4)
        if is_gif:
            scale = self.config.integer("gif_scale", scale, 1, 3)
        normalized_layout = normalize_layout(layout or self.config.default_layout)
        if normalized_layout not in {"auto", "single"}:
            raise RenderFailure(
                "invalid_layout", f"未知布局 {normalized_layout}，仅支持 auto、single"
            )
        fixed_page = self._fixed_page(metadata, style_overrides)
        return RenderOptions(
            html_content=html,
            output_image_path=output,
            scale=scale,
            width=width,
            is_gif=is_gif,
            duration=self.gif_duration,
            fps=self.gif_fps,
            layout=normalized_layout,
            max_page_height=self.config.integer("max_page_height", 3200, 400, 20_000),
            max_pages=self.config.integer("max_pages", 8, 1, 30),
            max_output_bytes=self.config.integer(
                "max_output_bytes", 6 * 1024 * 1024, 100_000, 50 * 1024 * 1024
            ),
            show_page_numbers=self.config.boolean("show_page_numbers", True),
            page_number_bottom_margin=self.page_number_bottom_margin(metadata),
            allow_remote_assets=trusted and self.config.boolean("allow_remote_assets"),
            fixed_page_size=fixed_page,
        )

    def _fixed_page(self, metadata: dict, overrides: dict | None) -> dict | None:
        value = metadata.get("fixed_page")
        if not isinstance(value, dict):
            return None
        fixed = dict(value)
        raw_margin = (
            overrides.get("paper_margin_y")
            if overrides and "paper_margin_y" in overrides
            else self.config.get("paper_margin_y", int(fixed.get("top_margin", 76)))
        )
        try:
            margin = int(raw_margin)
        except (TypeError, ValueError):
            margin = int(fixed.get("top_margin", 76))
        margin = max(24, min(margin, 180))
        fixed["top_margin"] = margin
        fixed["bottom_margin"] = margin
        fixed["content_height"] = max(400, int(fixed.get("height", 1123)) - 2 * margin)
        return fixed

    @staticmethod
    def page_number_bottom_margin(metadata: dict) -> int:
        return {"knowledge": 24, "custom": 8}.get(str(metadata.get("scene", "")), 20)

    async def run_browser(self, options: RenderOptions) -> BrowserRenderResult:
        normalized = self.normalize_browser_result(
            await html_to_image_playwright(options), options.output_image_path
        )
        if not normalized and normalized.error_code == "browser_error":
            logger.warning("[HTML渲染] 浏览器渲染失败，重建后重试一次")
            normalized = self.normalize_browser_result(
                await html_to_image_playwright(options), options.output_image_path
            )
        if not normalized:
            if normalized.error_code == "browser_error":
                self.browser_failure_count += 1
                cooldown = self.config.number(
                    "browser_failure_cooldown_seconds", 30.0, 1.0, 300.0
                )
                self.browser_cooldown_until = time.monotonic() + cooldown
            raise RenderFailure(
                normalized.error_code or "browser_error",
                normalized.error_message or "Chromium 渲染失败",
            )
        return normalized

    def _finalize(
        self, normalized: BrowserRenderResult, template_name: str, layout: str
    ) -> RenderResult:
        self.browser_failure_count = 0
        self.browser_cooldown_until = 0.0
        images = [
            Image.fromFileSystem(path)
            for path in normalized.paths
            if os.path.isfile(path)
        ]
        if not images:
            raise RenderFailure("browser_error", "浏览器未生成任何图片")
        self.schedule_delete(*normalized.paths)
        self.last_metrics = {
            **normalized.metrics,
            "template": template_name,
            "layout": layout,
            "image_count": len(images),
        }
        self.last_error = {}
        return RenderResult(
            images=images,
            template=template_name,
            warnings=normalized.warnings,
            metrics=self.last_metrics,
        )

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        limit = self.config.integer("max_concurrent_renders", 2, 1, 16)
        state = self._semaphore_state
        if state is None or state[0] is not loop or state[1] != limit:
            semaphore = asyncio.Semaphore(limit)
            self._semaphore_state = (loop, limit, semaphore)
            return semaphore
        return state[2]

    @staticmethod
    def normalize_browser_result(result, output_path: str) -> BrowserRenderResult:
        if isinstance(result, BrowserRenderResult):
            return result
        if result:
            paths = [output_path] if os.path.isfile(output_path) else []
            base, extension = os.path.splitext(output_path)
            page = 2
            while os.path.isfile(f"{base}_p{page}{extension}"):
                paths.append(f"{base}_p{page}{extension}")
                page += 1
            gif_path = f"{base}.gif"
            if os.path.isfile(gif_path):
                paths.append(gif_path)
            return BrowserRenderResult(success=bool(paths), paths=paths)
        return BrowserRenderResult(
            success=False,
            error_code="browser_error",
            error_message="Chromium 渲染失败",
        )

    def _record_error(self, code: str, message: str) -> None:
        self.last_error = {
            "code": code,
            "message": message,
            "timestamp": int(time.time()),
        }

    def snapshot(self) -> RenderRuntimeSnapshot:
        remaining = max(0, int(self.browser_cooldown_until - time.monotonic()))
        return RenderRuntimeSnapshot(
            active_renders=self.active_renders,
            queued_renders=self.queued_renders,
            last_metrics=dict(self.last_metrics),
            last_error=dict(self.last_error),
            cooldown_seconds=remaining,
        )

    def cleanup_cache(self, max_age_seconds: int = 300) -> None:
        now = time.time()
        removed = 0
        try:
            for filename in os.listdir(self.image_cache_dir):
                path = os.path.join(self.image_cache_dir, filename)
                if (
                    os.path.isfile(path)
                    and now - os.path.getmtime(path) > max_age_seconds
                ):
                    os.remove(path)
                    removed += 1
            if removed:
                logger.info(f"[HTML渲染] 已清理 {removed} 个缓存文件")
        except Exception as exc:
            logger.warning(f"[HTML渲染] 清理缓存失败: {exc}")

    @staticmethod
    def schedule_delete(*paths: str) -> None:
        async def delete_later():
            await asyncio.sleep(300)
            for path in paths:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

        asyncio.create_task(delete_later())

    @staticmethod
    def format_failure(exc: Exception) -> str:
        if not isinstance(exc, RenderFailure):
            return f"渲染失败：{exc}"
        labels = {
            "invalid_content": "内容无效",
            "invalid_template": "模板无效",
            "invalid_layout": "布局无效",
            "resource_limit": "资源超限",
            "queue_full": "队列已满",
            "timeout": "渲染超时",
            "browser_error": "浏览器故障",
            "browser_cooldown": "浏览器冷却",
            "internal_error": "内部错误",
        }
        return f"渲染失败（{labels.get(exc.code, exc.code or '失败')}）：{exc.message}"
