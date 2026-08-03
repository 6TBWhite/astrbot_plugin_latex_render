"""Typed configuration access and WebUI configuration metadata."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


CLASSIC_STYLE_VARS = [
    ("classic_body_padding", "--classic-body-padding", "px"),
    ("classic_page_padding_y", "--classic-page-padding-y", "px"),
    ("classic_page_padding_x", "--classic-page-padding-x", "px"),
    ("classic_font_size", "--classic-font-size", "px"),
    ("classic_line_height", "--classic-line-height", ""),
    ("classic_h1_size", "--classic-h1-size", "px"),
    ("classic_h2_size", "--classic-h2-size", "px"),
    ("classic_h3_size", "--classic-h3-size", "px"),
]

PAPER_STYLE_VARS = [
    ("paper_margin_x", "--paper-margin-x", "px"),
    ("paper_font_size", "--paper-font-size", "px"),
    ("paper_line_height", "--paper-line-height", ""),
    ("paper_h1_size", "--paper-h1-size", "px"),
    ("paper_h2_size", "--paper-h2-size", "px"),
    ("paper_h3_size", "--paper-h3-size", "px"),
]

STYLE_CONTROL_SPECS = {
    "classic_body_padding": {
        "label": "外圈边距",
        "default": 18,
        "min": 0,
        "max": 48,
        "step": 1,
        "unit": "px",
    },
    "classic_page_padding_y": {
        "label": "画布上下留白",
        "default": 32,
        "min": 8,
        "max": 96,
        "step": 1,
        "unit": "px",
    },
    "classic_page_padding_x": {
        "label": "画布左右留白",
        "default": 28,
        "min": 8,
        "max": 96,
        "step": 1,
        "unit": "px",
    },
    "classic_font_size": {
        "label": "正文字号",
        "default": 22,
        "min": 12,
        "max": 34,
        "step": 1,
        "unit": "px",
    },
    "classic_line_height": {
        "label": "正文行高",
        "default": 1.8,
        "min": 1.2,
        "max": 2.4,
        "step": 0.05,
        "unit": "",
    },
    "classic_h1_size": {
        "label": "一级标题",
        "default": 31,
        "min": 20,
        "max": 48,
        "step": 1,
        "unit": "px",
    },
    "classic_h2_size": {
        "label": "二级标题",
        "default": 26,
        "min": 18,
        "max": 42,
        "step": 1,
        "unit": "px",
    },
    "classic_h3_size": {
        "label": "三级标题",
        "default": 23,
        "min": 16,
        "max": 36,
        "step": 1,
        "unit": "px",
    },
    "paper_margin_x": {
        "label": "左右页边距",
        "default": 76,
        "min": 32,
        "max": 160,
        "step": 1,
        "unit": "px",
    },
    "paper_margin_y": {
        "label": "上下页边距",
        "default": 76,
        "min": 24,
        "max": 180,
        "step": 1,
        "unit": "px",
    },
    "paper_font_size": {
        "label": "正文字号",
        "default": 16,
        "min": 12,
        "max": 24,
        "step": 1,
        "unit": "px",
    },
    "paper_line_height": {
        "label": "正文行高",
        "default": 1.75,
        "min": 1.2,
        "max": 2.4,
        "step": 0.05,
        "unit": "",
    },
    "paper_h1_size": {
        "label": "一级标题",
        "default": 24,
        "min": 18,
        "max": 40,
        "step": 1,
        "unit": "px",
    },
    "paper_h2_size": {
        "label": "二级标题",
        "default": 20,
        "min": 16,
        "max": 34,
        "step": 1,
        "unit": "px",
    },
    "paper_h3_size": {
        "label": "三级标题",
        "default": 18,
        "min": 14,
        "max": 30,
        "step": 1,
        "unit": "px",
    },
}

WEB_CONFIG_SPECS = {
    "default_template": {
        "label": "默认模板",
        "type": "select",
        "default": "",
        "hint": "未显式指定模板时使用；留空则自动选择第一个可用模板。",
    },
    "default_layout": {
        "label": "默认布局",
        "type": "select",
        "default": "auto",
        "options": ["auto", "single"],
        "option_labels": ["auto · 超长时分页", "single · 单张长图"],
        "hint": "auto 仅在内容超过分页高度时分页；single 输出单张长图。固定纸张尺寸由 Paper 模板决定。",
    },
    "max_page_height": {
        "label": "自动分页高度",
        "type": "number",
        "default": 3200,
        "min": 1200,
        "max": 6000,
        "step": 100,
        "unit": "CSS px",
        "hint": "auto 超过该高度后按顶层语义块装箱到固定高度页面；普通聊天建议 2400–4000，默认 3200。固定 A4 模板不受影响。",
    },
    "render_width": {
        "label": "渲染宽度",
        "type": "number",
        "default": 600,
        "min": 320,
        "max": 1600,
        "step": 1,
        "hint": "控制普通模板的 CSS 排版宽度；越宽，每行容纳的内容越多。",
    },
    "render_scale": {
        "label": "清晰度倍数",
        "type": "number",
        "default": 2,
        "min": 1,
        "max": 4,
        "step": 1,
        "hint": "提高输出分辨率；倍数越高越清晰，也会增加渲染耗时和图片体积。",
    },
    "enable_markdown": {
        "label": "Markdown 渲染",
        "type": "boolean",
        "default": True,
        "hint": "将标题、列表、引用、代码块和表格等 Markdown 语法转换为排版内容。",
    },
    "enable_math": {
        "label": "LaTeX 数学公式",
        "type": "boolean",
        "default": True,
        "hint": "启用离线 MathJax，渲染行内公式、块公式和常见 LaTeX 环境。",
    },
    "enable_code_highlight": {
        "label": "代码高亮与语言标识",
        "type": "boolean",
        "default": True,
        "hint": "高亮显式标注语言的 Markdown 围栏代码块，并在右上角显示语言名称。",
    },
    "show_page_numbers": {
        "label": "多页显示页码",
        "type": "boolean",
        "default": True,
        "hint": "分页输出时在每张图片右下角标注当前页和总页数。",
    },
    "max_input_chars": {
        "label": "最大输入字符数",
        "type": "number",
        "default": 50_000,
        "min": 100,
        "max": 500_000,
        "step": 100,
        "hint": "超过此长度会拒绝渲染，避免单个任务占用过多内存和浏览器资源。",
    },
    "render_timeout_seconds": {
        "label": "渲染超时",
        "type": "number",
        "default": 30,
        "min": 5,
        "max": 180,
        "step": 1,
        "unit": "秒",
        "hint": "限制任务从排队到 Chromium 排版完成的最长等待时间；超时会中止并返回明确提示。",
    },
    "max_pages": {
        "label": "单次最多页数",
        "type": "number",
        "default": 8,
        "min": 1,
        "max": 30,
        "step": 1,
        "hint": "分页结果超过此页数时拒绝输出，防止一次消息生成过多图片。",
    },
    "max_concurrent_renders": {
        "label": "最大并发渲染",
        "type": "number",
        "default": 2,
        "min": 1,
        "max": 16,
        "step": 1,
        "hint": "允许同时进入 Chromium 的任务数；公开机器人通常建议设置为 1–3。",
    },
    "trusted_html_mode": {
        "label": "可信 HTML/CSS 模式",
        "type": "boolean",
        "default": False,
        "danger": True,
        "hint": "允许更完整的 HTML/CSS，仅适合可信内容和私人部署；公开机器人不建议开启。",
    },
    "allow_remote_assets": {
        "label": "允许远程资源",
        "type": "boolean",
        "default": False,
        "danger": True,
        "hint": "允许模板加载远程资源，必须同时开启可信模式；可能产生隐私和内网访问风险。",
    },
}


def normalize_layout(value: object) -> str:
    layout = str(value or "").strip().lower()
    return "auto" if layout == "paged" else layout


class RenderConfig:
    """Live typed facade over AstrBot's mutable configuration mapping."""

    def __init__(self, raw: MutableMapping[str, Any]):
        self.raw = raw

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def boolean(self, key: str, default: bool = False) -> bool:
        return bool(self.raw.get(key, default))

    def integer(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.raw.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    def number(self, key: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(self.raw.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    @property
    def default_layout(self) -> str:
        value = normalize_layout(self.raw.get("default_layout", "auto"))
        return value if value in {"auto", "single"} else "auto"

    def web_payload(self, templates: list[str]) -> list[dict]:
        fields = []
        for key, definition in WEB_CONFIG_SPECS.items():
            item = {"key": key, **definition}
            item["value"] = self.raw.get(key, definition["default"])
            if key == "default_template":
                item["options"] = [""] + templates
                item["option_labels"] = ["自动选择"] + templates
            elif key == "default_layout" and item["value"] not in item["options"]:
                item["value"] = "auto"
            fields.append(item)
        return fields

    def normalize_web_values(self, values: dict, templates: list[str]) -> dict:
        normalized: dict[str, Any] = {}
        for key, raw_value in values.items():
            spec = WEB_CONFIG_SPECS.get(str(key))
            if not spec:
                continue
            if spec["type"] == "boolean":
                if not isinstance(raw_value, bool):
                    raise ValueError(f"{spec['label']} 必须是布尔值")
                normalized[key] = raw_value
                continue
            if spec["type"] == "select":
                value = str(raw_value or "").strip()
                if key == "default_layout":
                    value = normalize_layout(value)
                options = (
                    [""] + templates
                    if key == "default_template"
                    else list(spec.get("options", []))
                )
                if value not in options:
                    raise ValueError(f"{spec['label']} 的选项无效")
                normalized[key] = value
                continue
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{spec['label']} 必须是数字") from exc
            number = max(float(spec["min"]), min(number, float(spec["max"])))
            normalized[key] = (
                int(number) if isinstance(spec["default"], int) else number
            )
        trusted = normalized.get("trusted_html_mode", self.boolean("trusted_html_mode"))
        if normalized.get("allow_remote_assets") and not trusted:
            raise ValueError("允许远程资源前必须先开启可信 HTML/CSS 模式")
        return normalized

    def normalize_style_values(self, values: dict, allowed: set[str]) -> dict:
        normalized: dict[str, Any] = {}
        for key, raw_value in values.items():
            spec = STYLE_CONTROL_SPECS.get(str(key))
            if not spec or key not in allowed:
                continue
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{spec['label']} 必须是数字") from exc
            number = max(float(spec["min"]), min(number, float(spec["max"])))
            normalized[key] = (
                int(number) if isinstance(spec["default"], int) else round(number, 3)
            )
        return normalized

    def save(self, values: dict) -> None:
        for key, value in values.items():
            self.raw[key] = value
        saver = getattr(self.raw, "save_config", None)
        if callable(saver):
            saver()
