# renderer.py
# HTML → 图片渲染（Playwright），支持静态 PNG 与 GIF 动画（时间轴跳帧）
# 使用浏览器实例池避免重复启动 Chromium

import asyncio
import io
import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

from astrbot.api import logger

from .models import BrowserRenderResult

# ==================== 本地字体映射 ====================

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ASSETS_DIR = os.path.join(_PLUGIN_ROOT, "assets")
_FONT_MANIFEST: Dict[str, str] = {}  # URL -> 本地绝对路径
_FONT_MANIFEST_LOADED = False


def _load_font_manifest():
    """加载字体清单（URL -> 本地文件路径映射）"""
    global _FONT_MANIFEST, _FONT_MANIFEST_LOADED
    if _FONT_MANIFEST_LOADED:
        return

    manifest_path = os.path.join(_ASSETS_DIR, "fonts", "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # 转换为绝对路径
            for url, rel_path in raw.items():
                abs_path = os.path.join(_ASSETS_DIR, rel_path)
                if os.path.exists(abs_path):
                    _FONT_MANIFEST[url] = abs_path
            logger.info(f"[HTML渲染] 已加载 {len(_FONT_MANIFEST)} 个本地字体映射")
        except Exception as e:
            logger.warning(f"[HTML渲染] 加载字体清单失败: {e}")
    else:
        logger.debug(
            "[HTML渲染] 未找到字体清单 assets/fonts/manifest.json，将使用系统字体"
        )

    _FONT_MANIFEST_LOADED = True


def _get_font_mime(path: str) -> str:
    """根据文件扩展名返回 MIME 类型"""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
    }.get(ext, "application/octet-stream")


# GIF 合成支持
try:
    from PIL import Image as PILImage, ImageChops, ImageDraw

    GIF_AVAILABLE = True
except ImportError:
    GIF_AVAILABLE = False
    logger.warning(
        "HTML渲染插件: Pillow 未安装，GIF 动画功能将不可用。"
        "可通过 pip install Pillow 安装。"
    )

# ==================== 浏览器实例池 ====================

_playwright_instance = None
_browser_instance = None
_browser_lock = asyncio.Lock()
_CAPTURE_BOTTOM_PADDING = 24
_PAGINATION_BOTTOM_BUFFER = 40
_last_browser_error = ""
_last_render_seconds = 0.0


async def init_browser():
    """初始化浏览器实例（插件启动时调用）"""
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
        except Exception as e:
            if _playwright_instance is not None:
                try:
                    await _playwright_instance.stop()
                except Exception:
                    pass
            _playwright_instance = None
            _browser_instance = None
            raise RuntimeError(f"Playwright 浏览器实例启动失败: {e}") from e


async def close_browser():
    """关闭浏览器实例（插件停止时调用）"""
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
    """获取浏览器实例，若不存在则自动创建"""
    global _browser_instance
    if _browser_instance is None or not _browser_instance.is_connected():
        await init_browser()
    return _browser_instance


# ==================== 动画区域检测 ====================


async def _measure_capture_height(page) -> int:
    """Measure a conservative capture height so the last line is not clipped."""
    height = await page.evaluate(
        f"""() => {{
            const docEl = document.documentElement;
            const body = document.body;
            const heights = [
                docEl ? docEl.scrollHeight : 0,
                docEl ? docEl.offsetHeight : 0,
                docEl ? docEl.clientHeight : 0,
                body ? body.scrollHeight : 0,
                body ? body.offsetHeight : 0,
                body ? body.clientHeight : 0,
            ];

            let maxBottom = 0;
            for (const el of document.querySelectorAll('*')) {{
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const bottom = rect.bottom + window.scrollY;
                if (bottom > maxBottom) {{
                    maxBottom = bottom;
                }}
            }}

            return Math.max(...heights, Math.ceil(maxBottom + {_CAPTURE_BOTTOM_PADDING}));
        }}"""
    )
    return max(int(height), 200)


async def _stabilize_layout(page, rounds: int = 3) -> int:
    """
    Wait for fonts/layout to settle and return a capture height.
    Re-checking a few times avoids late bottom reflow.
    """
    stable_height = 200

    for _ in range(rounds):
        await page.evaluate(
            """() => {
                const mathScript = document.getElementById('astrbot-mathjax-script');
                if (!mathScript || window.__ASTR_MATH_READY__) {
                    return Promise.resolve();
                }
                return new Promise(resolve => {
                    const started = Date.now();
                    const tick = () => {
                        if (window.__ASTR_MATH_READY__ || Date.now() - started > 15000) {
                            resolve();
                            return;
                        }
                        setTimeout(tick, 50);
                    };
                    tick();
                });
            }"""
        )
        await page.evaluate(
            """() => {
                if (!document.fonts || !document.fonts.ready) {
                    return Promise.resolve();
                }
                return document.fonts.ready.catch(() => {});
            }"""
        )
        await page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        stable_height = await _measure_capture_height(page)
        await asyncio.sleep(0.05)

    return stable_height


async def _prepare_page_for_capture(page, width: int) -> int:
    """Resize the viewport to the measured content height, then verify once more."""
    full_height = await _stabilize_layout(page)
    await page.set_viewport_size({"width": width, "height": full_height})
    return await _stabilize_layout(page)


async def _install_network_policy(page, allow_remote_assets: bool = False) -> None:
    """Keep rendering offline unless an administrator explicitly opts in."""

    async def _route(route):
        url = route.request.url
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme in {"data", "blob", "about"}:
            await route.continue_()
            return
        if allow_remote_assets and scheme in {"http", "https"}:
            await route.continue_()
            return
        await route.abort()

    await page.route("**/*", _route)


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
                "breakable": str(last.get("tag", "")).lower() not in _HEADING_TAGS,
            }
        )
        index = last_index + 1
    return groups


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

    blocks = await page.evaluate(
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
                    text_length: (el.textContent || "").replace(/\\s+/g, " ").trim().length,
                    keep_target: (
                        ["pre", "table", "ul", "ol", "blockquote", "figure"].includes(
                            el.tagName.toLowerCase()
                        )
                        || el.classList.contains("astr-math-block")
                        || Boolean(el.querySelector('mjx-container[display="true"]'))
                    ),
                };
            }).filter(item => item.bottom > item.top);
        }"""
    )
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


def _add_page_number(path: str, page_number: int, page_count: int) -> None:
    if not GIF_AVAILABLE or page_count <= 1:
        return
    try:
        with PILImage.open(path) as source:
            image = source.convert("RGB")
            draw = ImageDraw.Draw(image)
            label = f"{page_number} / {page_count}"
            bbox = draw.textbbox((0, 0), label)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            x = max(8, image.width - width - 22)
            y = max(8, image.height - height - 18)
            draw.rounded_rectangle(
                (x - 8, y - 5, x + width + 8, y + height + 5),
                radius=6,
                fill=(255, 255, 255),
                outline=(190, 190, 190),
            )
            draw.text((x, y), label, fill=(70, 70, 70))
            image.save(path, "JPEG", quality=90, optimize=True)
    except Exception as exc:
        logger.warning(f"[HTML渲染] 添加页码失败: {exc}")


def _add_continuation_marker(
    path: str, continues_from_previous: bool, continues_to_next: bool
) -> None:
    if not GIF_AVAILABLE or not (continues_from_previous or continues_to_next):
        return
    try:
        with PILImage.open(path) as source:
            image = source.convert("RGB")
            draw = ImageDraw.Draw(image)
            if continues_from_previous:
                draw.rounded_rectangle(
                    (14, 12, 124, 36),
                    radius=5,
                    fill=(255, 255, 255),
                    outline=(190, 190, 190),
                )
                draw.text((22, 18), "continued", fill=(80, 80, 80))
            if continues_to_next:
                y = max(12, image.height - 38)
                draw.rounded_rectangle(
                    (14, y, 132, y + 24),
                    radius=5,
                    fill=(255, 255, 255),
                    outline=(190, 190, 190),
                )
                draw.text((22, y + 6), "continues...", fill=(80, 80, 80))
            image.save(path, "JPEG", quality=90, optimize=True)
    except Exception as exc:
        logger.warning(f"[HTML渲染] 添加续页标记失败: {exc}")


def _pad_fixed_canvas(
    path: str,
    page_width: int,
    page_height: int,
    top_margin: int,
    scale: int,
) -> None:
    """Place a semantic page slice on a same-size white paper canvas."""

    if not GIF_AVAILABLE:
        raise ValueError("固定纸张分页需要 Pillow")
    pixel_width = max(1, int(page_width * scale))
    pixel_height = max(1, int(page_height * scale))
    y = max(0, int(top_margin * scale))
    with PILImage.open(path) as source:
        slice_image = source.convert("RGB")
        if slice_image.width != pixel_width:
            ratio = pixel_width / max(1, slice_image.width)
            slice_image = slice_image.resize(
                (pixel_width, max(1, int(slice_image.height * ratio))),
                PILImage.Resampling.LANCZOS,
            )
        available_height = max(1, pixel_height - y)
        if slice_image.height > available_height:
            slice_image = slice_image.crop((0, 0, slice_image.width, available_height))
        canvas = PILImage.new("RGB", (pixel_width, pixel_height), "white")
        canvas.paste(slice_image, (0, y))
        canvas.save(path, "JPEG", quality=92, optimize=True)


def _enforce_image_budget(path: str, max_output_bytes: int) -> str | None:
    """Compress an oversized JPEG and report a warning when quality is reduced."""

    if max_output_bytes <= 0 or not os.path.isfile(path):
        return None
    if os.path.getsize(path) <= max_output_bytes:
        return None
    if not GIF_AVAILABLE:
        raise ValueError("图片超过体积上限，且 Pillow 不可用，无法自动压缩")

    with PILImage.open(path) as source:
        image = source.convert("RGB")
        for quality in (84, 78, 72, 66, 60):
            image.save(path, "JPEG", quality=quality, optimize=True)
            if os.path.getsize(path) <= max_output_bytes:
                return f"图片超过体积预算，已将 JPEG 质量调整为 {quality}"

        while (
            os.path.getsize(path) > max_output_bytes
            and image.width > 480
            and image.height > 480
        ):
            image = image.resize(
                (max(1, int(image.width * 0.85)), max(1, int(image.height * 0.85))),
                PILImage.Resampling.LANCZOS,
            )
            image.save(path, "JPEG", quality=66, optimize=True)

    if os.path.getsize(path) > max_output_bytes:
        raise ValueError(
            f"图片压缩后仍有 {os.path.getsize(path)} 字节，超过上限 {max_output_bytes}"
        )
    return "图片超过体积预算，已自动降低分辨率"


def _cleanup_output_family(output_image_path: str) -> None:
    directory = os.path.dirname(output_image_path) or "."
    base = os.path.splitext(os.path.basename(output_image_path))[0]
    try:
        for name in os.listdir(directory):
            stem, extension = os.path.splitext(name)
            if extension.lower() not in {".jpg", ".jpeg", ".gif", ".png"}:
                continue
            if stem == base or stem.startswith(f"{base}_p"):
                try:
                    os.remove(os.path.join(directory, name))
                except OSError:
                    pass
    except OSError:
        pass


def get_renderer_status() -> dict:
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
    """
    检测页面中的动画区域。
    策略1：JS 查找带 animation 的元素的公共父容器
    策略2：像素对比回退
    """
    # ====== 策略1：JS 查找动画容器 ======
    try:
        clip_from_js = await page.evaluate("""() => {
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

            return {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height
            };
        }""")

        if clip_from_js:
            pad = 10
            clip = {
                "x": max(0, clip_from_js["x"] - pad),
                "y": max(0, clip_from_js["y"] - pad),
                "width": min(clip_from_js["width"] + pad * 2, viewport_width),
                "height": min(clip_from_js["height"] + pad * 2, viewport_height),
            }

            page_area = viewport_width * viewport_height
            clip_area = clip["width"] * clip["height"]
            ratio = clip_area / page_area

            if ratio > 0.8:
                logger.info(f"[GIF] 动画容器占页面 {ratio * 100:.0f}%，不裁切")
                return None

            logger.info(
                f"[GIF] JS定位动画容器: {clip['width']:.0f}×{clip['height']:.0f} CSS px "
                f"(占比 {ratio * 100:.1f}%)"
            )
            return clip

    except Exception as e:
        logger.warning(f"[GIF] JS定位失败: {e}")

    # ====== 策略2：像素对比回退 ======
    try:
        has_animations = await page.evaluate("document.getAnimations().length > 0")
        if has_animations:
            await page.evaluate("""() => {
                document.getAnimations().forEach(a => {
                    a.pause();
                    a.currentTime = 0;
                });
            }""")
            await asyncio.sleep(0.05)
            raw_a = await page.screenshot(type="png")
            shot_a = PILImage.open(io.BytesIO(raw_a)).convert("RGB")

            await page.evaluate("""() => {
                document.getAnimations().forEach(a => {
                    a.currentTime = 2000;
                });
            }""")
            await asyncio.sleep(0.05)
            raw_b = await page.screenshot(type="png")
            shot_b = PILImage.open(io.BytesIO(raw_b)).convert("RGB")

            # 恢复播放
            await page.evaluate("document.getAnimations().forEach(a => a.play())")

            diff = ImageChops.difference(shot_a, shot_b).convert("L")
            diff = diff.point(lambda p: 255 if p > 3 else 0)
            bbox = diff.getbbox()

            if bbox:
                page_area = shot_a.width * shot_a.height
                region_w = bbox[2] - bbox[0]
                region_h = bbox[3] - bbox[1]
                ratio = region_w * region_h / page_area

                if ratio > 0.8:
                    logger.info(f"[GIF] 像素变化区域占页面 {ratio * 100:.0f}%，不裁切")
                    return None

                pad = int(30 * scale)
                clip = {
                    "x": max(0, bbox[0] - pad) / scale,
                    "y": max(0, bbox[1] - pad) / scale,
                    "width": min(region_w + pad * 2, shot_a.width) / scale,
                    "height": min(region_h + pad * 2, shot_a.height) / scale,
                }
                logger.info(
                    f"[GIF] 像素对比定位: {clip['width']:.0f}×{clip['height']:.0f} CSS px"
                )
                return clip

        logger.info("[GIF] 未检测到动画")
        return None

    except Exception as e:
        logger.warning(f"[GIF] 像素对比失败: {e}")
        return None


async def _get_animation_duration(page) -> float:
    """获取页面中最长动画的周期（毫秒）"""
    try:
        duration_ms = await page.evaluate("""() => {
            const anims = document.getAnimations();
            if (anims.length === 0) return 3000;
            let maxDuration = 0;
            for (const a of anims) {
                const timing = a.effect.getComputedTiming();
                const d = timing.duration || 0;
                if (d > maxDuration) maxDuration = d;
            }
            return maxDuration || 3000;
        }""")
        return float(duration_ms)
    except Exception:
        return 3000.0


# ==================== 主渲染函数 ====================


@dataclass
class RenderOptions:
    """浏览器渲染参数集合。"""

    html_content: str
    output_image_path: str
    scale: int = 2
    width: int = 600
    is_gif: bool = False
    duration: float = 3.0
    fps: int = 15
    layout: str = "auto"
    max_page_height: int = 3200
    max_pages: int = 8
    max_output_bytes: int = 6 * 1024 * 1024
    show_page_numbers: bool = True
    allow_remote_assets: bool = False
    fixed_page_size: dict | None = None


async def html_to_image_playwright(options: RenderOptions) -> BrowserRenderResult:
    """
    使用 Playwright 将 HTML 内容渲染成图片。
    复用浏览器实例，每次只创建新页面。
    GIF 模式使用时间轴跳帧：暂停动画 → seek到每帧时间点 → 截图，零等待。
    """
    html_content = options.html_content
    output_image_path = options.output_image_path
    scale = options.scale
    width = options.width
    is_gif = options.is_gif
    duration = options.duration
    fps = options.fps
    layout = options.layout
    max_page_height = options.max_page_height
    max_pages = options.max_pages
    max_output_bytes = options.max_output_bytes
    show_page_numbers = options.show_page_numbers
    allow_remote_assets = options.allow_remote_assets
    fixed_page_size = options.fixed_page_size

    import time as _time

    global _last_browser_error, _last_render_seconds
    _t_start = _time.perf_counter()

    page = None
    context = None
    try:
        browser = await _get_browser()
        if browser is None:
            logger.error("[HTML渲染] 无法获取浏览器实例，回退到独立模式")
            return await _fallback_render(
                html_content,
                output_image_path,
                scale,
                width,
                is_gif,
                duration,
                fps,
                max_output_bytes=max_output_bytes,
                allow_remote_assets=allow_remote_assets,
            )

        context = await browser.new_context(
            device_scale_factor=scale,
            viewport={"width": width, "height": 800},
        )
        page = await context.new_page()
        page.set_default_timeout(15_000)

        await _install_network_policy(page, allow_remote_assets)

        # ===== 字体路由映射：将 Google Fonts 请求重定向到本地文件 =====
        _load_font_manifest()

        async def _handle_font_route(route):
            """拦截字体请求，优先使用本地文件"""
            url = route.request.url
            local_path = _FONT_MANIFEST.get(url)

            if local_path and os.path.exists(local_path):
                # 本地字体存在，直接返回
                try:
                    with open(local_path, "rb") as f:
                        body = f.read()
                    await route.fulfill(
                        status=200,
                        content_type=_get_font_mime(local_path),
                        body=body,
                    )
                    return
                except Exception as e:
                    logger.warning(f"[HTML渲染] 读取本地字体失败 {local_path}: {e}")

            # 无本地映射或读取失败，阻断请求（避免网络延迟）
            await route.abort()

        # 拦截 Google Fonts 字体文件请求
        await page.route("**://fonts.gstatic.com/**", _handle_font_route)
        # 拦截 Google Fonts CSS 请求（如果模板仍有外部 <link>）
        await page.route("**://fonts.googleapis.com/**", lambda route: route.abort())

        _t_page = _time.perf_counter()

        # domcontentloaded 足够：纯本地 HTML 无外部资源需要等待
        await page.set_content(html_content, wait_until="domcontentloaded")

        # 等待一帧让 CSS 动画和布局稳定
        full_height = await _prepare_page_for_capture(page, width)

        _t_content = _time.perf_counter()
        logger.debug(
            f"[性能] 页面创建: {_t_page - _t_start:.3f}s, 内容加载: {_t_content - _t_page:.3f}s"
        )

        output_paths: list[str] = []
        warnings: list[str] = []

        if not is_gif:
            normalized_layout = str(layout or "auto").strip().lower()
            if normalized_layout not in {"auto", "single", "paged"}:
                normalized_layout = "auto"

            if fixed_page_size:
                normalized_layout = "paged"
                max_page_height = int(
                    fixed_page_size.get("content_height", max_page_height)
                )
            elif (
                normalized_layout == "single"
                and full_height > max_page_height * max_pages
            ):
                raise ValueError(
                    f"单页高度 {full_height}px 超过绝对上限 "
                    f"{max_page_height * max_pages}px"
                )

            should_paginate = normalized_layout == "paged" or (
                normalized_layout == "auto" and full_height > max_page_height
            )
            if should_paginate:
                bottom_buffer = (
                    0
                    if fixed_page_size
                    else min(
                        _PAGINATION_BOTTOM_BUFFER,
                        max(0, int(max_page_height) - 400),
                    )
                )
                slice_height_budget = max(400, int(max_page_height) - bottom_buffer)
                slices, hard_breaks = await _calculate_page_slices(
                    page,
                    full_height,
                    slice_height_budget,
                    max(1, int(max_pages)),
                )
                base, extension = os.path.splitext(output_image_path)
                extension = extension or ".jpg"
                for index, (start, end) in enumerate(slices, start=1):
                    path = (
                        output_image_path
                        if index == 1
                        else f"{base}_p{index}{extension}"
                    )
                    await page.screenshot(
                        path=path,
                        clip={
                            "x": 0,
                            "y": start,
                            "width": width,
                            "height": end - start,
                        },
                        type="jpeg",
                        quality=92,
                    )
                    output_paths.append(path)

                if fixed_page_size:
                    for path in output_paths:
                        _pad_fixed_canvas(
                            path,
                            int(fixed_page_size.get("width", width)),
                            int(fixed_page_size.get("height", 1123)),
                            int(fixed_page_size.get("top_margin", 76)),
                            scale,
                        )

                for index, path in enumerate(output_paths, start=1):
                    _add_continuation_marker(
                        path,
                        continues_from_previous=(index - 1) in hard_breaks,
                        continues_to_next=index in hard_breaks,
                    )

                if show_page_numbers and len(output_paths) > 1:
                    for index, path in enumerate(output_paths, start=1):
                        _add_page_number(path, index, len(output_paths))
            else:
                await page.screenshot(
                    path=output_image_path,
                    full_page=True,
                    type="jpeg",
                    quality=92,
                )
                output_paths.append(output_image_path)

            for path in output_paths:
                budget_warning = _enforce_image_budget(path, max_output_bytes)
                if budget_warning and budget_warning not in warnings:
                    warnings.append(budget_warning)

            _t_end = _time.perf_counter()
            logger.info(f"[性能] 静态渲染总耗时: {_t_end - _t_start:.3f}s")
        else:
            if not GIF_AVAILABLE:
                logger.warning("Pillow 未安装，回退到静态截图")
                await page.screenshot(path=output_image_path, full_page=True)
            else:
                # 展开视口到完整内容高度

                # 1. 先截完整静态图
                await page.screenshot(path=output_image_path, full_page=True)
                logger.info("[GIF] 已生成静态全页截图")

                # 2. 检测动画区域
                clip = await _detect_animated_region(page, scale, width, full_height)

                # 3. 如果有动画区域，用时间轴跳帧录制
                if clip:
                    gif_path = os.path.splitext(output_image_path)[0] + ".gif"

                    anim_duration_ms = await _get_animation_duration(page)
                    record_duration_ms = min(duration * 1000, anim_duration_ms)

                    frame_count = int(record_duration_ms / 1000 * fps)
                    frame_count = max(frame_count, 10)
                    frame_interval_ms = record_duration_ms / frame_count

                    logger.info(
                        f"[GIF] 时间轴跳帧模式：动画周期={anim_duration_ms:.0f}ms，"
                        f"录制={record_duration_ms:.0f}ms，{frame_count}帧，"
                        f"裁切={clip['width']:.0f}×{clip['height']:.0f}"
                    )

                    # 暂停所有动画
                    await page.evaluate(
                        "document.getAnimations().forEach(a => a.pause())"
                    )

                    frames = []
                    record_start = _time.perf_counter()

                    for i in range(frame_count):
                        target_time = i * frame_interval_ms
                        await page.evaluate(
                            f"document.getAnimations().forEach(a => a.currentTime = {target_time})"
                        )
                        await asyncio.sleep(0.02)

                        frame_bytes = await page.screenshot(
                            clip=clip, type="jpeg", quality=85
                        )
                        frame_img = PILImage.open(io.BytesIO(frame_bytes)).convert(
                            "RGB"
                        )
                        frame_img = frame_img.convert(
                            "P", palette=PILImage.ADAPTIVE, colors=256
                        )
                        frames.append(frame_img)

                    # 恢复播放
                    await page.evaluate(
                        "document.getAnimations().forEach(a => a.play())"
                    )

                    record_time = _time.perf_counter() - record_start
                    logger.info(
                        f"[GIF] 跳帧完成：{len(frames)}帧，耗时{record_time:.1f}s"
                    )

                    out_dir = os.path.dirname(output_image_path)
                    if out_dir:
                        os.makedirs(out_dir, exist_ok=True)

                    if frames:
                        compose_start = _time.perf_counter()
                        frame_display_ms = int(frame_interval_ms)
                        frames[0].save(
                            gif_path,
                            save_all=True,
                            append_images=frames[1:],
                            duration=frame_display_ms,
                            loop=0,
                            optimize=True,
                        )
                        compose_time = _time.perf_counter() - compose_start
                        logger.info(f"[GIF] 合成完成，耗时{compose_time:.1f}s")
                else:
                    logger.info("[GIF] 未检测到动画区域，仅输出静态图")

            _t_end = _time.perf_counter()
            logger.info(f"[性能] GIF渲染总耗时: {_t_end - _t_start:.3f}s")
            if os.path.exists(output_image_path):
                output_paths.append(output_image_path)
            gif_path = os.path.splitext(output_image_path)[0] + ".gif"
            if os.path.exists(gif_path):
                output_paths.append(gif_path)

        _last_browser_error = ""
        _last_render_seconds = _t_end - _t_start
        return BrowserRenderResult(
            success=True,
            paths=output_paths,
            warnings=warnings,
            metrics={
                "duration_seconds": round(_last_render_seconds, 3),
                "page_count": len(output_paths),
                "content_height": full_height,
                "layout": layout,
            },
        )

    except asyncio.CancelledError:
        _cleanup_output_family(output_image_path)
        raise
    except Exception as e:
        logger.error(f"Playwright 渲染失败: {e}")
        import traceback

        logger.error(traceback.format_exc())

        # 浏览器可能已崩溃，重置实例
        global _browser_instance
        _browser_instance = None
        _cleanup_output_family(output_image_path)
        _last_browser_error = str(e)
        _last_render_seconds = _time.perf_counter() - _t_start
        error_code = (
            "resource_limit"
            if isinstance(e, ValueError) and ("上限" in str(e) or "超过" in str(e))
            else "browser_error"
        )
        return BrowserRenderResult(
            success=False,
            error_code=error_code,
            error_message=str(e),
            metrics={"duration_seconds": round(_last_render_seconds, 3)},
        )

    finally:
        # 只关闭 context/page，不关闭浏览器
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
    """回退到独立浏览器模式（浏览器池不可用时）"""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(
                device_scale_factor=scale,
                viewport={"width": width, "height": 800},
            )
            page = await context.new_page()
            await _install_network_policy(page, allow_remote_assets)
            await page.set_content(html_content, wait_until="domcontentloaded")
            await _prepare_page_for_capture(page, width)
            await page.screenshot(
                path=output_image_path, full_page=True, type="jpeg", quality=92
            )
            warning = _enforce_image_budget(output_image_path, max_output_bytes)
            await browser.close()
            logger.info("[HTML渲染] 回退模式渲染完成（仅静态图）")
            return BrowserRenderResult(
                success=True,
                paths=[output_image_path],
                warnings=[warning] if warning else [],
                metrics={"fallback": True, "page_count": 1},
            )
    except Exception as e:
        logger.error(f"[HTML渲染] 回退渲染也失败: {e}")
        return BrowserRenderResult(
            success=False,
            error_code="browser_error",
            error_message=str(e),
        )
