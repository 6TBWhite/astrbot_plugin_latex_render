"""Template selection, configuration, and prompt guidance."""

from __future__ import annotations

import html as html_lib
import os

from astrbot.api import logger

from .config import CLASSIC_STYLE_VARS, PAPER_STYLE_VARS, RenderConfig
from .template_guidance import TemplateGuidanceBuilder
from .template_manager import TemplateManager
from .text_processing import markdown_to_html, nl2br, preserve_newlines


class TemplateService:
    """Coordinate template discovery, selection, styling, and guidance."""

    def __init__(
        self,
        manager: TemplateManager,
        config: RenderConfig,
        plugin_dir: str,
    ):
        self.manager = manager
        self.config = config
        self.plugin_dir = plugin_dir
        self.user_defaults: dict[str, str] = {}

    def refresh_schema_options(self) -> None:
        schema = getattr(self.config.raw, "schema", None)
        if not isinstance(schema, dict):
            return
        templates = self.available()
        field = schema.get("default_template")
        if isinstance(field, dict):
            field["options"] = [""] + templates
            field["enum"] = [""] + templates
            field["labels"] = ["自动使用第一个可用模板"] + templates
        background_field = schema.get("background_image")
        if isinstance(background_field, dict):
            images = self.background_images()
            background_field["options"] = [""] + images
            background_field["enum"] = [""] + images
            background_field["labels"] = ["不使用自定义背景"] + images

    def available(self) -> list[str]:
        getter = getattr(self.manager, "get_available_templates", None)
        templates = getter() if callable(getter) else []
        return templates if isinstance(templates, list) else []

    def require_available(self) -> list[str]:
        getter = getattr(self.manager, "require_available_templates", None)
        if callable(getter):
            return getter()
        templates = self.available()
        if templates:
            return templates
        template_dir = getattr(
            self.manager, "TEMPLATE_DIR", os.path.join(self.plugin_dir, "templates")
        )
        raise FileNotFoundError(
            f"未找到任何模板文件，请先在 {template_dir} 中放入至少一个 .html 模板"
        )

    def has(self, template_name: str | None) -> bool:
        if not template_name:
            return False
        checker = getattr(self.manager, "has_template", None)
        return (
            bool(checker(template_name))
            if callable(checker)
            else template_name in self.available()
        )

    def background_images(self) -> list[str]:
        extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        results: list[str] = []
        background_dir = os.path.join(self.plugin_dir, "assets", "backgrounds")
        for root, _, files in os.walk(background_dir):
            for filename in files:
                if os.path.splitext(filename)[1].lower() not in extensions:
                    continue
                absolute = os.path.join(root, filename)
                relative = os.path.relpath(absolute, self.plugin_dir)
                results.append(relative.replace("\\", "/"))
        return sorted(set(results))

    def _resolve_existing(self, name: str | None, source: str) -> str | None:
        if not name:
            return None
        if self.has(name):
            return name
        raise ValueError(f"{source} 指向的模板不存在: {name}")

    def default(self, user_id: str | None = None) -> str:
        available = self.require_available()
        if user_id:
            user_template = self.user_defaults.get(user_id)
            if user_template and self.has(user_template):
                return user_template
            if user_template:
                self.user_defaults.pop(user_id, None)
                logger.warning(
                    f"[HTML渲染] 用户 {user_id} 的默认模板不存在，已清除失效配置: {user_template}"
                )
        configured = str(self.config.get("default_template", "") or "").strip() or None
        resolved = self._resolve_existing(configured, "default_template")
        return resolved or available[0]

    def select(
        self,
        content: str,
        specified_template: str | None = None,
        user_id: str | None = None,
    ) -> str:
        del content
        self.require_available()
        if specified_template:
            return self._resolve_existing(specified_template, "specified template")
        return self.default(user_id)

    def set_user_default(self, user_id: str, template_name: str) -> None:
        if not self.has(template_name):
            raise ValueError(f"模板不存在: {template_name}")
        self.user_defaults[user_id] = template_name

    def current(self, preferred: str = "") -> str:
        available = self.available()
        if not available:
            return ""
        return preferred if preferred in available else available[0]

    def guidance(
        self,
        current_template: str = "",
        template: str = "",
        *,
        compact: bool = False,
    ) -> str:
        return TemplateGuidanceBuilder(self.manager, self.available()).build(
            current_template=current_template,
            template=template,
            compact=compact,
        )

    def style_definitions(self, template_name: str) -> list[tuple[str, str, str]]:
        metadata = self.manager.get_template_metadata(template_name)
        family = str(metadata.get("base_template", template_name) or template_name)
        return {"classic": CLASSIC_STYLE_VARS, "paper": PAPER_STYLE_VARS}.get(
            family, []
        )

    def inject_style_vars(
        self,
        html: str,
        template_name: str,
        overrides: dict | None = None,
    ) -> str:
        lines = []
        for config_key, variable_name, unit in self.style_definitions(template_name):
            value = (
                overrides.get(config_key)
                if overrides and config_key in overrides
                else self.config.get(config_key)
            )
            if value is None:
                continue
            try:
                float(value)
            except (TypeError, ValueError):
                continue
            lines.append(f"    {variable_name}: {value}{unit};")
        if not lines:
            return html
        block = (
            '<style id="astrbot-classic-vars">\n:root {\n'
            + "\n".join(lines)
            + "\n}\n</style>"
        )
        head_end = html.lower().rfind("</head>")
        return (
            html[:head_end] + block + "\n" + html[head_end:]
            if head_end != -1
            else block + "\n" + html
        )

    def apply(
        self,
        content: str,
        template_name: str,
        is_raw_html: bool = False,
        *,
        style_overrides: dict | None = None,
        template_html_override: str | None = None,
    ) -> str:
        template = (
            template_html_override
            if template_html_override is not None
            else self.manager.load_template(template_name)
        )
        if is_raw_html:
            return self.inject_style_vars(
                template.replace("{{content}}", content), template_name, style_overrides
            )
        if self.config.boolean("enable_markdown", True):
            content = markdown_to_html(content, safe=True)
            return self.inject_style_vars(
                template.replace("{{content}}", content), template_name, style_overrides
            )
        content = nl2br(preserve_newlines(html_lib.escape(content, quote=False)))
        return self.inject_style_vars(
            template.replace("{{content}}", content), template_name, style_overrides
        )
