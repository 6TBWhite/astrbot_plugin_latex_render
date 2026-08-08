"""Static, paginated, and animated browser capture."""

import asyncio
import io
import os
import time
from typing import Optional

from astrbot.api import logger

from .models import RenderOptions
from .page_prepare import CAPTURE_BOTTOM_PADDING
from .postprocess import (
    PIL_AVAILABLE,
    PILImage,
    enforce_image_budgets,
    postprocess_paginated_images,
)

if PIL_AVAILABLE:
    from PIL import ImageChops
else:
    ImageChops = None

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _should_keep_with_next(current: dict, following: dict) -> bool:
    """Keep headings and short lead-ins with the block they introduce."""

    current_tag = str(current.get("tag", "")).lower()
    following_tag = str(following.get("tag", "")).lower()
    if current_tag in _HEADING_TAGS:
        return following_tag not in _HEADING_TAGS
    if current_tag != "p" or not bool(following.get("keep_target", False)):
        return False
    return (
        0 < int(current.get("text_length", 0)) <= 120
        and int(current.get("height", 0)) <= 240
    )


def _group_pagination_blocks(blocks: list[dict]) -> list[dict]:
    """Build atomic pagination groups without modifying the rendered DOM."""

    groups: list[dict] = []
    index = 0
    while index < len(blocks):
        first = blocks[index]
        last_index = index
        while last_index + 1 < len(blocks) and _should_keep_with_next(
            blocks[last_index], blocks[last_index + 1]
        ):
            last_index += 1
        last = blocks[last_index]
        groups.append(
            {
                "top": int(first["top"]),
                "bottom": int(last["bottom"]),
                "breakable": str(last.get("tag", "")).lower()
                not in _HEADING_TAGS,
                "block_indexes": list(range(index, last_index + 1)),
            }
        )
        index = last_index + 1
    return groups


async def _collect_pagination_blocks(page) -> list[dict]:
    """Measure direct children of the content container."""

    return await page.evaluate(
        """() => {
            const root = document.querySelector('.content') || document.body;
            if (!root) return [];
            const children = Array.from(root.children);
            return children.map((el) => {
                const rect = el.getBoundingClientRect();
                return {
                    top: Math.max(0, Math.floor(rect.top + window.scrollY)),
                    bottom: Math.max(0, Math.ceil(rect.bottom + window.scrollY)),
                    tag: el.tagName.toLowerCase(),
                    height: Math.max(0, Math.ceil(rect.height)),
                    text_length: (el.textContent || '').replace(/\\s+/g, ' ').trim().length,
                    keep_target: (
                        ['pre', 'table', 'ul', 'ol', 'blockquote', 'figure'].includes(
                            el.tagName.toLowerCase()
                        )
                        || el.classList.contains('astr-math-block')
                        || Boolean(el.querySelector('mjx-container[display="true"]'))
                    ),
                };
            }).filter(item => item.bottom > item.top);
        }"""
    )


def _pack_into_pages(
    groups: list[dict], page_height: int, max_pages: int
) -> tuple[list[list[int]], set[int]]:
    """Pack atomic groups into fixed-height pages; return per-page indexes."""

    pages: list[list[int]] = []
    hard_pages: set[int] = set()
    page_top: int | None = None
    current: list[int] | None = None
    for group in groups:
        top = int(group["top"])
        bottom = int(group["bottom"])
        if current is None:
            page_top = top
            current = []
        if bottom - page_top <= page_height:
            current.extend(group["block_indexes"])
        else:
            pages.append(current)
            page_top = top
            current = list(group["block_indexes"])
            if bottom - top > page_height:
                hard_pages.add(len(pages))
    if current is not None:
        pages.append(current)
    if len(pages) > max_pages:
        raise ValueError(f"分页结果为 {len(pages)} 页，超过最多 {max_pages} 页")
    return pages, hard_pages


async def _measure_page_content_height(page, page_height: int) -> int:
    """Return the usable content height of a fixed-height page container."""

    chrome = await page.evaluate(
        """() => {
            const root = document.querySelector('.content');
            if (!root) return 0;
            const cs = getComputedStyle(root.parentElement);
            return (
                parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) +
                parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth)
            );
        }"""
    )
    return max(400, int(page_height) - int(chrome or 0))


async def _inject_page_containers(
    page,
    page_block_indexes: list[list[int]],
    page_height: int,
) -> list[tuple[int, int]]:
    """Move blocks into cloned fixed-height page containers."""

    result = await page.evaluate(
        """([assignments, pageHeight]) => {
            const root = document.querySelector('.content');
            if (!root || root.dataset.paginationDone) return null;
            root.dataset.paginationDone = '1';
            const children = Array.from(root.children);
            const pageTpl = root.parentElement;
            const container = pageTpl.parentElement;
            assignments.forEach((blockIndexes, pi) => {
                let pageEl = pageTpl;
                if (pi > 0) {
                    pageEl = pageTpl.cloneNode(true);
                    const contentEl = pageEl.querySelector('.content');
                    while (contentEl.firstChild) {
                        contentEl.removeChild(contentEl.firstChild);
                    }
                    container.appendChild(pageEl);
                }
                const contentEl = pageEl.querySelector('.content');
                for (const bi of blockIndexes) {
                    contentEl.appendChild(children[bi]);
                }
                pageEl.style.height = pageHeight + 'px';
                pageEl.style.overflow = 'hidden';
                pageEl.style.boxShadow = 'none';
            });
            const pages = Array.from(container.children).filter(
                (el) => el.classList.contains('page') || el.classList.contains('aurora-card')
            );
            return pages.map((el) => {
                const r = el.getBoundingClientRect();
                return [Math.round(r.top + window.scrollY), Math.round(r.bottom + window.scrollY)];
            });
        }""",
        [page_block_indexes, page_height],
    )
    if result is None:
        raise RuntimeError("分页容器注入失败")
    return [(int(top), int(bottom)) for top, bottom in result]


async def _calculate_page_slices(
    page,
    full_height: int,
    max_page_height: int,
    max_pages: int,
) -> tuple[list[tuple[int, int]], set[int]]:
    """Find page breaks near semantic block boundaries."""

    if full_height <= max_page_height:
        return [(0, full_height)], set()
    if full_height > max_page_height * max_pages:
        raise ValueError(
            f"页面高度 {full_height}px 超过分页上限 "
            f"{max_page_height * max_pages}px（最多 {max_pages} 页）"
        )

    blocks = await _collect_pagination_blocks(page)
    groups = _group_pagination_blocks(blocks)
    slices: list[tuple[int, int]] = []
    hard_breaks: set[int] = set()
    start = 0
    minimum_fill = max(320, int(max_page_height * 0.45))
    while start < full_height:
        target = min(full_height, start + max_page_height)
        if target >= full_height:
            slices.append((start, full_height))
            break

        break_at = 0
        for group in groups:
            top = int(group["top"])
            bottom = int(group["bottom"])
            if (
                bool(group.get("breakable", True))
                and start + minimum_fill <= bottom <= target
            ):
                break_at = max(break_at, bottom)
            elif (
                not break_at
                and start + minimum_fill <= top <= target
                and bottom > target
            ):
                break_at = top

        hard_split = break_at <= start
        end = break_at if not hard_split else target
        slices.append((start, end))
        if hard_split:
            hard_breaks.add(len(slices))
        start = end

    if len(slices) > max_pages:
        raise ValueError(f"分页结果为 {len(slices)} 页，超过最多 {max_pages} 页")
    return slices, hard_breaks


def _resolve_static_layout(
    options: RenderOptions, full_height: int
) -> tuple[str, int, bool]:
    """Normalize the layout and decide whether pagination is required."""

    layout = str(options.layout or "auto").strip().lower()
    if layout not in {"auto", "single", "paged"}:
        layout = "auto"

    page_height = options.max_page_height
    if options.fixed_page_size:
        layout = "paged"
        page_height = int(options.fixed_page_size.get("content_height", page_height))
    elif layout == "single" and full_height > page_height * options.max_pages:
        raise ValueError(
            f"单页高度 {full_height}px 超过绝对上限 {page_height * options.max_pages}px"
        )

    should_paginate = layout == "paged" or (
        layout == "auto" and full_height > page_height
    )
    return layout, page_height, should_paginate


async def _plan_page_capture(
    page,
    options: RenderOptions,
    full_height: int,
    page_height: int,
) -> tuple[list[tuple[int, int]] | None, set[int]]:
    """Build either clip windows or DOM page containers for capture."""

    if options.fixed_page_size:
        page_windows, hard_breaks = await _calculate_page_slices(
            page,
            full_height,
            max(400, int(page_height)),
            max(1, int(options.max_pages)),
        )
        return page_windows, hard_breaks

    blocks = await _collect_pagination_blocks(page)
    groups = _group_pagination_blocks(blocks)
    usable_height = await _measure_page_content_height(page, int(page_height))
    usable_height = max(400, usable_height - CAPTURE_BOTTOM_PADDING)
    page_block_indexes, hard_pages = _pack_into_pages(
        groups, usable_height, max(1, int(options.max_pages))
    )
    hard_breaks = {page_index + 1 for page_index in hard_pages}
    if len(page_block_indexes) > 1:
        await _inject_page_containers(page, page_block_indexes, int(page_height))
        return None, hard_breaks
    return [(0, full_height)], hard_breaks


def _page_output_path(output_image_path: str, index: int) -> str:
    """Keep the legacy page naming scheme used by existing consumers."""

    base, extension = os.path.splitext(output_image_path)
    extension = extension or ".jpg"
    return output_image_path if index == 1 else f"{base}_p{index}{extension}"


async def _capture_paginated_images(
    page,
    options: RenderOptions,
    full_height: int,
    page_height: int,
) -> list[str]:
    """Capture all pages, then hand them to the post-processing phase."""

    page_windows, hard_breaks = await _plan_page_capture(
        page, options, full_height, page_height
    )
    page_count = (
        len(page_windows)
        if page_windows is not None
        else await page.locator(".page, .aurora-card").count()
    )
    output_paths: list[str] = []
    for index in range(page_count):
        path = _page_output_path(options.output_image_path, index)
        if page_windows is not None:
            start, end = page_windows[index]
            await page.screenshot(
                path=path,
                clip={
                    "x": 0,
                    "y": start,
                    "width": options.width,
                    "height": end - start,
                },
                type="jpeg",
                quality=92,
            )
        else:
            await (
                page.locator(".page, .aurora-card")
                .nth(index)
                .screenshot(path=path, type="jpeg", quality=92)
            )
        output_paths.append(path)

    postprocess_paginated_images(
        output_paths,
        hard_breaks,
        fixed_page_size=options.fixed_page_size,
        width=options.width,
        scale=options.scale,
        show_page_numbers=options.show_page_numbers,
        page_number_bottom_margin=options.page_number_bottom_margin,
    )
    return output_paths


async def render_static_images(
    page,
    options: RenderOptions,
    full_height: int,
    started_at: float,
) -> tuple[list[str], list[str]]:
    """Capture static output and apply the configured image budget."""

    _, page_height, should_paginate = _resolve_static_layout(options, full_height)
    if should_paginate:
        output_paths = await _capture_paginated_images(
            page, options, full_height, page_height
        )
    else:
        await page.screenshot(
            path=options.output_image_path,
            full_page=True,
            type="jpeg",
            quality=92,
        )
        output_paths = [options.output_image_path]

    warnings = enforce_image_budgets(output_paths, options.max_output_bytes)
    logger.info(f"[性能] 静态渲染总耗时: {time.perf_counter() - started_at:.3f}s")
    return output_paths, warnings


async def _detect_css_animated_region(
    page,
    viewport_width: int,
    viewport_height: int,
) -> tuple[bool, Optional[dict]]:
    """Locate a CSS animation container; report whether the strategy decided."""

    try:
        bounds = await page.evaluate(
            """() => {
                const allEls = document.querySelectorAll('*');
                const animatedEls = [];
                for (const el of allEls) {
                    const style = getComputedStyle(el);
                    if (style.animationName && style.animationName !== 'none') {
                        animatedEls.push(el);
                    }
                }
                if (animatedEls.length === 0) return null;

                let container = animatedEls[0].parentElement;
                while (container && container !== document.body) {
                    const style = getComputedStyle(container);
                    if (style.overflow === 'hidden' || style.overflowX === 'hidden') {
                        break;
                    }
                    container = container.parentElement;
                }
                if (!container || container === document.body) {
                    container = animatedEls[0].parentElement;
                }

                const rect = container.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return null;
                return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
            }"""
        )
        if not bounds:
            return False, None

        padding = 10
        clip = {
            "x": max(0, bounds["x"] - padding),
            "y": max(0, bounds["y"] - padding),
            "width": min(bounds["width"] + padding * 2, viewport_width),
            "height": min(bounds["height"] + padding * 2, viewport_height),
        }
        ratio = clip["width"] * clip["height"] / (
            viewport_width * viewport_height
        )
        if ratio > 0.8:
            logger.info(f"[GIF] 动画容器占页面 {ratio * 100:.0f}%，不裁切")
            return True, None

        logger.info(
            f"[GIF] JS定位动画容器: {clip['width']:.0f}×{clip['height']:.0f} CSS px "
            f"(占比 {ratio * 100:.1f}%)"
        )
        return True, clip
    except Exception as exc:
        logger.warning(f"[GIF] JS定位失败: {exc}")
        return False, None


async def _detect_pixel_animated_region(page, scale: int) -> Optional[dict]:
    """Locate animation through a two-frame pixel comparison."""

    try:
        has_animations = await page.evaluate("document.getAnimations().length > 0")
        if has_animations:
            await page.evaluate(
                """() => {
                    document.getAnimations().forEach(a => {
                        a.pause();
                        a.currentTime = 0;
                    });
                }"""
            )
            await asyncio.sleep(0.05)
            raw_a = await page.screenshot(type="png")
            shot_a = PILImage.open(io.BytesIO(raw_a)).convert("RGB")

            await page.evaluate(
                """() => {
                    document.getAnimations().forEach(a => {
                        a.currentTime = 2000;
                    });
                }"""
            )
            await asyncio.sleep(0.05)
            raw_b = await page.screenshot(type="png")
            shot_b = PILImage.open(io.BytesIO(raw_b)).convert("RGB")
            await page.evaluate("document.getAnimations().forEach(a => a.play())")

            diff = ImageChops.difference(shot_a, shot_b).convert("L")
            diff = diff.point(lambda pixel: 255 if pixel > 3 else 0)
            bbox = diff.getbbox()
            if bbox:
                page_area = shot_a.width * shot_a.height
                region_width = bbox[2] - bbox[0]
                region_height = bbox[3] - bbox[1]
                ratio = region_width * region_height / page_area
                if ratio > 0.8:
                    logger.info(
                        f"[GIF] 像素变化区域占页面 {ratio * 100:.0f}%，不裁切"
                    )
                    return None

                padding = int(30 * scale)
                clip = {
                    "x": max(0, bbox[0] - padding) / scale,
                    "y": max(0, bbox[1] - padding) / scale,
                    "width": min(region_width + padding * 2, shot_a.width) / scale,
                    "height": min(region_height + padding * 2, shot_a.height)
                    / scale,
                }
                logger.info(
                    f"[GIF] 像素对比定位: {clip['width']:.0f}×{clip['height']:.0f} CSS px"
                )
                return clip

        logger.info("[GIF] 未检测到动画")
        return None
    except Exception as exc:
        logger.warning(f"[GIF] 像素对比失败: {exc}")
        return None


async def _detect_animated_region(
    page,
    scale: int,
    viewport_width: int,
    viewport_height: int,
) -> Optional[dict]:
    """Prefer CSS metadata, then fall back to pixel comparison."""

    decided, clip = await _detect_css_animated_region(
        page, viewport_width, viewport_height
    )
    if decided:
        return clip
    return await _detect_pixel_animated_region(page, scale)


async def _get_animation_duration(page) -> float:
    """Return the longest browser animation duration in milliseconds."""

    try:
        duration_ms = await page.evaluate(
            """() => {
                const anims = document.getAnimations();
                if (anims.length === 0) return 3000;
                let maxDuration = 0;
                for (const animation of anims) {
                    const timing = animation.effect.getComputedTiming();
                    const duration = timing.duration || 0;
                    if (duration > maxDuration) maxDuration = duration;
                }
                return maxDuration || 3000;
            }"""
        )
        return float(duration_ms)
    except Exception:
        return 3000.0


async def _record_gif_animation(
    page, options: RenderOptions, clip: dict
) -> str | None:
    """Record the detected region by seeking the browser timeline."""

    gif_path = os.path.splitext(options.output_image_path)[0] + ".gif"
    animation_duration_ms = await _get_animation_duration(page)
    record_duration_ms = min(options.duration * 1000, animation_duration_ms)
    frame_count = max(int(record_duration_ms / 1000 * options.fps), 10)
    frame_interval_ms = record_duration_ms / frame_count
    logger.info(
        f"[GIF] 时间轴跳帧模式：动画周期={animation_duration_ms:.0f}ms，"
        f"录制={record_duration_ms:.0f}ms，{frame_count}帧，"
        f"裁切={clip['width']:.0f}×{clip['height']:.0f}"
    )

    await page.evaluate("document.getAnimations().forEach(a => a.pause())")
    frames = []
    record_started_at = time.perf_counter()
    for index in range(frame_count):
        target_time = index * frame_interval_ms
        await page.evaluate(
            f"document.getAnimations().forEach(a => a.currentTime = {target_time})"
        )
        await asyncio.sleep(0.02)
        frame_bytes = await page.screenshot(clip=clip, type="jpeg", quality=85)
        frame = PILImage.open(io.BytesIO(frame_bytes)).convert("RGB")
        frames.append(frame.convert("P", palette=PILImage.ADAPTIVE, colors=256))
    await page.evaluate("document.getAnimations().forEach(a => a.play())")
    logger.info(
        f"[GIF] 跳帧完成：{len(frames)}帧，"
        f"耗时{time.perf_counter() - record_started_at:.1f}s"
    )

    output_dir = os.path.dirname(options.output_image_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    if not frames:
        return None

    compose_started_at = time.perf_counter()
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=int(frame_interval_ms),
        loop=0,
        optimize=True,
    )
    logger.info(f"[GIF] 合成完成，耗时{time.perf_counter() - compose_started_at:.1f}s")
    return gif_path


async def render_gif_images(
    page,
    options: RenderOptions,
    full_height: int,
    started_at: float,
) -> tuple[list[str], list[str]]:
    """Capture a full static image and an optional animated crop."""

    if not PIL_AVAILABLE:
        logger.warning("Pillow 未安装，回退到静态截图")
        await page.screenshot(path=options.output_image_path, full_page=True)
    else:
        await page.screenshot(path=options.output_image_path, full_page=True)
        logger.info("[GIF] 已生成静态全页截图")
        clip = await _detect_animated_region(
            page, options.scale, options.width, full_height
        )
        if clip:
            await _record_gif_animation(page, options, clip)
        else:
            logger.info("[GIF] 未检测到动画区域，仅输出静态图")

    logger.info(f"[性能] GIF渲染总耗时: {time.perf_counter() - started_at:.3f}s")
    output_paths = []
    if os.path.exists(options.output_image_path):
        output_paths.append(options.output_image_path)
    gif_path = os.path.splitext(options.output_image_path)[0] + ".gif"
    if os.path.exists(gif_path):
        output_paths.append(gif_path)
    return output_paths, []


_render_static_images = render_static_images
_render_gif_images = render_gif_images
