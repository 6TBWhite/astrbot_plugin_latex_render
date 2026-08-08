"""Browser-page preparation before any capture or pagination measurement."""

import asyncio
import json
import os
from typing import Dict

from astrbot.api import logger

from .math_quality import run_math_quality_gate

CAPTURE_BOTTOM_PADDING = 24
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ASSETS_DIR = os.path.join(_PLUGIN_ROOT, "assets")
_FONT_MANIFEST: Dict[str, str] = {}
_FONT_MANIFEST_LOADED = False


def _load_font_manifest() -> None:
    """Load the external-font URL to local-file mapping once."""

    global _FONT_MANIFEST, _FONT_MANIFEST_LOADED
    if _FONT_MANIFEST_LOADED:
        return

    manifest_path = os.path.join(_ASSETS_DIR, "fonts", "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as manifest_file:
                raw = json.load(manifest_file)
            for url, relative_path in raw.items():
                absolute_path = os.path.join(_ASSETS_DIR, relative_path)
                if os.path.exists(absolute_path):
                    _FONT_MANIFEST[url] = absolute_path
            logger.info(f"[HTML渲染] 已加载 {len(_FONT_MANIFEST)} 个本地字体映射")
        except Exception as exc:
            logger.warning(f"[HTML渲染] 加载字体清单失败: {exc}")
    else:
        logger.debug(
            "[HTML渲染] 未找到字体清单 assets/fonts/manifest.json，将使用系统字体"
        )
    _FONT_MANIFEST_LOADED = True


def _get_font_mime(path: str) -> str:
    """Return the font MIME type inferred from a file extension."""

    extension = os.path.splitext(path)[1].lower()
    return {
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
    }.get(extension, "application/octet-stream")


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

            return Math.max(...heights, Math.ceil(maxBottom + {CAPTURE_BOTTOM_PADDING}));
        }}"""
    )
    return max(int(height), 200)


async def _stabilize_layout(page, rounds: int = 3) -> int:
    """Wait for code highlighting and fonts to settle, then measure the page."""

    stable_height = 200
    for _ in range(rounds):
        await page.evaluate(
            """() => {
                const loader = document.querySelector('[data-astrbot-code-highlight-loader]');
                if (!loader || window.__ASTR_CODE_HIGHLIGHT_READY__) {
                    return Promise.resolve();
                }
                return new Promise(resolve => {
                    const started = Date.now();
                    const tick = () => {
                        if (window.__ASTR_CODE_HIGHLIGHT_READY__) {
                            resolve();
                            return;
                        }
                        if (Date.now() - started > 3000) {
                            window.__ASTR_CODE_HIGHLIGHT_READY__ = true;
                            resolve();
                            return;
                        }
                        setTimeout(tick, 25);
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
    """Resize the viewport to measured content height and verify it once more."""

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


async def _handle_font_route(route) -> None:
    """Serve a mapped local font or block the external request."""

    url = route.request.url
    local_path = _FONT_MANIFEST.get(url)
    if local_path and os.path.exists(local_path):
        try:
            with open(local_path, "rb") as font_file:
                body = font_file.read()
            await route.fulfill(
                status=200,
                content_type=_get_font_mime(local_path),
                body=body,
            )
            return
        except Exception as exc:
            logger.warning(f"[HTML渲染] 读取本地字体失败 {local_path}: {exc}")
    await route.abort()


async def _install_font_routes(page) -> None:
    """Install deterministic local-only routes for Google Fonts assets."""

    _load_font_manifest()
    await page.route("**://fonts.gstatic.com/**", _handle_font_route)
    await page.route("**://fonts.googleapis.com/**", lambda route: route.abort())


async def prepare_page(page, html_content: str, width: int) -> tuple[int, dict]:
    """Load HTML, run the MathJax gate once, and stabilize capture geometry."""

    await page.set_content(html_content, wait_until="domcontentloaded")
    math_metrics = await run_math_quality_gate(page)
    full_height = await _prepare_page_for_capture(page, width)
    return full_height, math_metrics


_load_and_prepare_page = prepare_page
