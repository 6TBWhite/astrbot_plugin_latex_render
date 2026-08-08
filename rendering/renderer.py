"""Coordinate browser lifecycle, page preparation, capture, and post-processing."""

import asyncio
import time
from typing import Optional

from astrbot.api import logger

from .capture import (
    _calculate_page_slices,
    _capture_paginated_images,
    _collect_pagination_blocks,
    _detect_css_animated_region,
    _detect_pixel_animated_region,
    _get_animation_duration,
    _group_pagination_blocks,
    _inject_page_containers,
    _measure_page_content_height,
    _pack_into_pages,
    _page_output_path,
    _plan_page_capture,
    _record_gif_animation,
    _resolve_static_layout,
    _should_keep_with_next,
    render_gif_images,
    render_static_images,
)
from .math_quality import MathQualityError
from .models import BrowserRenderResult, RenderOptions
from .page_prepare import (
    CAPTURE_BOTTOM_PADDING,
    _get_font_mime,
    _handle_font_route,
    _install_font_routes,
    _install_network_policy,
    _load_font_manifest,
    _measure_capture_height,
    _prepare_page_for_capture,
    _stabilize_layout,
    prepare_page,
)
from .postprocess import (
    PIL_AVAILABLE,
    _add_continuation_marker,
    _add_page_number,
    _cleanup_output_family,
    _enforce_image_budget,
    _load_page_number_font,
    _pad_fixed_canvas,
    _page_number_color,
    _page_number_font_size,
    _page_number_position,
)

_CAPTURE_BOTTOM_PADDING = CAPTURE_BOTTOM_PADDING
GIF_AVAILABLE = PIL_AVAILABLE

_playwright_instance = None
_browser_instance = None
_browser_lock = asyncio.Lock()
_last_browser_error = ""
_last_render_seconds = 0.0


async def init_browser() -> None:
    """Initialize the reusable browser instance."""

    global _playwright_instance, _browser_instance
    async with _browser_lock:
        if _browser_instance is not None:
            try:
                if _browser_instance.is_connected():
                    return
            except Exception:
                pass
            try:
                await _browser_instance.close()
            except Exception:
                pass
            _browser_instance = None

        try:
            from playwright.async_api import async_playwright

            if _playwright_instance is None:
                _playwright_instance = await async_playwright().start()
            _browser_instance = await _playwright_instance.chromium.launch()
            logger.info("[HTML渲染] 浏览器实例已启动（复用模式）")
        except Exception as exc:
            if _playwright_instance is not None:
                try:
                    await _playwright_instance.stop()
                except Exception:
                    pass
            _playwright_instance = None
            _browser_instance = None
            raise RuntimeError(f"Playwright 浏览器实例启动失败: {exc}") from exc


async def close_browser() -> None:
    """Close the reusable browser instance."""

    global _playwright_instance, _browser_instance
    async with _browser_lock:
        if _browser_instance is not None:
            try:
                await _browser_instance.close()
            except Exception:
                pass
            _browser_instance = None
        if _playwright_instance is not None:
            try:
                await _playwright_instance.stop()
            except Exception:
                pass
            _playwright_instance = None
        logger.info("[HTML渲染] 浏览器实例已关闭")


async def _get_browser():
    """Return the reusable browser, creating it when needed."""

    global _browser_instance
    if _browser_instance is None or not _browser_instance.is_connected():
        await init_browser()
    return _browser_instance


def get_renderer_status() -> dict:
    """Return a diagnostics snapshot without mutating browser state."""

    connected = False
    if _browser_instance is not None:
        try:
            connected = bool(_browser_instance.is_connected())
        except Exception:
            connected = False
    return {
        "browser_connected": connected,
        "last_browser_error": _last_browser_error,
        "last_render_seconds": round(_last_render_seconds, 3),
    }


async def _detect_animated_region(
    page,
    scale: int,
    viewport_width: int,
    viewport_height: int,
) -> Optional[dict]:
    """Compatibility wrapper retaining monkey-patchable detector hooks."""

    decided, clip = await _detect_css_animated_region(
        page, viewport_width, viewport_height
    )
    if decided:
        return clip
    return await _detect_pixel_animated_region(page, scale)


_load_and_prepare_page = prepare_page
_render_static_images = render_static_images
_render_gif_images = render_gif_images


async def html_to_image_playwright(options: RenderOptions) -> BrowserRenderResult:
    """Render HTML by coordinating the prepare, capture, and post-process phases."""

    global _browser_instance, _last_browser_error, _last_render_seconds
    started_at = time.perf_counter()
    context = None
    try:
        browser = await _get_browser()
        if browser is None:
            logger.error("[HTML渲染] 无法获取浏览器实例，回退到独立模式")
            return await _fallback_render(
                options.html_content,
                options.output_image_path,
                options.scale,
                options.width,
                options.is_gif,
                options.duration,
                options.fps,
                max_output_bytes=options.max_output_bytes,
                allow_remote_assets=options.allow_remote_assets,
            )

        context = await browser.new_context(
            device_scale_factor=options.scale,
            viewport={"width": options.width, "height": 800},
        )
        page = await context.new_page()
        page.set_default_timeout(15_000)
        await _install_network_policy(page, options.allow_remote_assets)
        await _install_font_routes(page)

        page_started_at = time.perf_counter()
        full_height, math_metrics = await prepare_page(
            page, options.html_content, options.width
        )
        content_ready_at = time.perf_counter()
        logger.debug(
            f"[性能] 页面创建: {page_started_at - started_at:.3f}s, "
            f"内容加载: {content_ready_at - page_started_at:.3f}s"
        )

        if options.is_gif:
            output_paths, warnings = await render_gif_images(
                page, options, full_height, started_at
            )
        else:
            output_paths, warnings = await render_static_images(
                page, options, full_height, started_at
            )

        _last_browser_error = ""
        _last_render_seconds = time.perf_counter() - started_at
        return BrowserRenderResult(
            success=True,
            paths=output_paths,
            warnings=warnings,
            metrics={
                "duration_seconds": round(_last_render_seconds, 3),
                "page_count": len(output_paths),
                "content_height": full_height,
                "layout": options.layout,
                **math_metrics,
            },
        )
    except asyncio.CancelledError:
        _cleanup_output_family(options.output_image_path)
        raise
    except Exception as exc:
        if isinstance(exc, MathQualityError):
            logger.warning(f"[HTML渲染] 公式质量门禁未通过: {exc.message}")
        else:
            logger.error(f"Playwright 渲染失败: {exc}")
            import traceback

            logger.error(traceback.format_exc())

        if not isinstance(exc, MathQualityError):
            _browser_instance = None
        _cleanup_output_family(options.output_image_path)
        _last_browser_error = str(exc)
        _last_render_seconds = time.perf_counter() - started_at
        if isinstance(exc, MathQualityError):
            error_code = exc.code
            error_metrics = exc.metrics
        elif isinstance(exc, ValueError) and (
            "上限" in str(exc) or "超过" in str(exc)
        ):
            error_code = "resource_limit"
            error_metrics = {}
        else:
            error_code = "browser_error"
            error_metrics = {}
        return BrowserRenderResult(
            success=False,
            error_code=error_code,
            error_message=str(exc),
            metrics={
                "duration_seconds": round(_last_render_seconds, 3),
                **error_metrics,
            },
        )
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass


async def _fallback_render(
    html_content: str,
    output_image_path: str,
    scale: int,
    width: int,
    is_gif: bool,
    duration: float,
    fps: int,
    max_output_bytes: int = 6 * 1024 * 1024,
    allow_remote_assets: bool = False,
) -> BrowserRenderResult:
    """Use an isolated browser when the shared pool is unavailable."""

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            context = await browser.new_context(
                device_scale_factor=scale,
                viewport={"width": width, "height": 800},
            )
            page = await context.new_page()
            await _install_network_policy(page, allow_remote_assets)
            _, math_metrics = await prepare_page(page, html_content, width)
            await page.screenshot(
                path=output_image_path,
                full_page=True,
                type="jpeg",
                quality=92,
            )
            warning = _enforce_image_budget(output_image_path, max_output_bytes)
            await browser.close()
            logger.info("[HTML渲染] 回退模式渲染完成（仅静态图）")
            return BrowserRenderResult(
                success=True,
                paths=[output_image_path],
                warnings=[warning] if warning else [],
                metrics={"fallback": True, "page_count": 1, **math_metrics},
            )
    except MathQualityError as exc:
        logger.warning(f"[HTML渲染] 回退渲染未通过公式质量门禁: {exc.message}")
        _cleanup_output_family(output_image_path)
        return BrowserRenderResult(
            success=False,
            error_code=exc.code,
            error_message=exc.message,
            metrics=exc.metrics,
        )
    except Exception as exc:
        logger.error(f"[HTML渲染] 回退渲染也失败: {exc}")
        return BrowserRenderResult(
            success=False,
            error_code="browser_error",
            error_message=str(exc),
        )
