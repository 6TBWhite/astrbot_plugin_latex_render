"""MathJax readiness and output quality checks run before image capture."""

from __future__ import annotations

import re
import time


MATH_GATE_TIMEOUT_MS = 15_000
_MATH_ERROR_LIMIT = 180


class MathQualityError(RuntimeError):
    """A deterministic MathJax content/load failure that must not be retried."""

    def __init__(self, code: str, message: str, metrics: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.metrics = metrics or {}


def _safe_math_error(value: object) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"(?i)\b[a-z]:[\\/][^\s]+", "[path]", text)
    text = re.sub(r"(?<!\w)/(?:[^/\s]+/)+[^\s]+", "[path]", text)
    if len(text) <= _MATH_ERROR_LIMIT:
        return text
    return text[: _MATH_ERROR_LIMIT - 3].rstrip() + "..."


def validate_math_snapshot(snapshot: dict, elapsed: float) -> dict:
    state = str(snapshot.get("state", "") or "")
    items = snapshot.get("items", [])
    if not isinstance(items, list):
        items = []
    metrics = {
        "math_count": len(items),
        "math_gate_seconds": round(elapsed, 3),
    }
    if state == "skipped":
        return metrics
    if state == "timeout":
        raise MathQualityError(
            "math_timeout", "MathJax 在 15 秒内未完成公式排版", metrics
        )
    if state != "ready":
        raise MathQualityError("math_load_failed", "MathJax 加载或启动失败", metrics)

    for fallback_index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise MathQualityError(
                "math_incomplete", f"第 {fallback_index} 个公式未生成完整 SVG", metrics
            )
        index = int(item.get("index", fallback_index) or fallback_index)
        detail = _safe_math_error(item.get("error"))
        if detail:
            if detail.startswith("Undefined control sequence"):
                command = detail.removeprefix("Undefined control sequence").strip()
                message = f"第 {index} 个公式存在未知命令 {command}"
            else:
                message = f"第 {index} 个公式语法错误：{detail}"
            raise MathQualityError("math_invalid", message, metrics)
        if not item.get("rendered") or not item.get("svg"):
            raise MathQualityError(
                "math_incomplete", f"第 {index} 个公式未生成完整 SVG", metrics
            )
        try:
            width = float(item.get("width", 0))
            height = float(item.get("height", 0))
        except (TypeError, ValueError):
            width = height = 0
        if width <= 0 or height <= 0:
            raise MathQualityError(
                "math_incomplete", f"第 {index} 个公式生成了零尺寸 SVG", metrics
            )
        if item.get("overflow"):
            raise MathQualityError(
                "math_overflow", f"第 {index} 个公式超出图片可见区域", metrics
            )
    return metrics


async def run_math_quality_gate(page, timeout_ms: int = MATH_GATE_TIMEOUT_MS) -> dict:
    """Wait once for MathJax, then reject incomplete or visibly clipped formulas."""

    started_at = time.perf_counter()
    snapshot = await page.evaluate(
        """async (timeoutMs) => {
            const loader = document.querySelector('[data-astrbot-mathjax-loader]');
            if (!loader) return {state: 'skipped', items: []};

            const started = Date.now();
            while (true) {
                const status = window.__ASTR_MATH_STATUS__;
                if (status && status.state && status.state !== 'pending') break;
                if (Date.now() - started >= timeoutMs) {
                    return {state: 'timeout', items: []};
                }
                await new Promise(resolve => setTimeout(resolve, 25));
            }

            const status = window.__ASTR_MATH_STATUS__ || {};
            if (status.state !== 'ready') {
                return {state: status.state || 'failed', error: status.error || '', items: []};
            }

            const viewportWidth = document.documentElement.clientWidth;
            const wrappers = Array.from(document.querySelectorAll(
                '.astr-math-inline, .astr-math-block'
            ));
            const items = wrappers.map((wrapper, offset) => {
                const container = wrapper.querySelector('mjx-container[jax="SVG"]');
                const errorNode = container
                    ? container.querySelector('[data-mjx-error]')
                    : null;
                const svg = container ? container.querySelector('svg') : null;
                const rect = svg ? svg.getBoundingClientRect() : null;
                const host = wrapper.parentElement || wrapper.closest('.content')
                    || document.documentElement;
                const hostRect = host.getBoundingClientRect();
                const scrollOverflow = wrapper.classList.contains('astr-math-block')
                    && wrapper.scrollWidth > wrapper.clientWidth + 1;
                const outsideHost = rect
                    ? rect.left < Math.max(0, hostRect.left) - 1
                        || rect.right > Math.min(viewportWidth, hostRect.right) + 1
                    : false;
                return {
                    index: offset + 1,
                    rendered: Boolean(container),
                    svg: Boolean(svg),
                    error: errorNode ? errorNode.getAttribute('data-mjx-error') || '' : '',
                    width: rect ? rect.width : 0,
                    height: rect ? rect.height : 0,
                    overflow: scrollOverflow || outsideHost,
                };
            });
            return {state: 'ready', items};
        }""",
        timeout_ms,
    )
    if not isinstance(snapshot, dict):
        snapshot = {"state": "failed", "error": "MathJax 状态无效", "items": []}
    return validate_math_snapshot(snapshot, time.perf_counter() - started_at)
