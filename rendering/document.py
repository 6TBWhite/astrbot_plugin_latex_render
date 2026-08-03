"""Build final browser-ready HTML documents."""

from __future__ import annotations

import re

from ..config import RenderConfig
from ..template_system.service import TemplateService
from .assets import HtmlAssets
from .models import RenderFailure
from .text import contains_math


class HtmlDocumentBuilder:
    def __init__(
        self,
        config: RenderConfig,
        templates: TemplateService,
        assets: HtmlAssets,
    ):
        self.config = config
        self.templates = templates
        self.assets = assets

    def build(
        self,
        content: str,
        specified_template: str | None,
        user_id: str | None,
        style_overrides: dict | None,
        template_html_override: str | None,
    ) -> tuple[str, dict, str, bool]:
        try:
            template_name = self.templates.select(content, specified_template, user_id)
        except (ValueError, FileNotFoundError) as exc:
            raise RenderFailure("invalid_template", str(exc)) from exc
        metadata = self.templates.manager.get_template_metadata(template_name)
        trusted = self.config.boolean("trusted_html_mode")
        raw_html = trusted and bool(
            re.search(r"<(?:style|html)\b", content, re.IGNORECASE)
        )
        html = self.templates.apply(
            content,
            template_name,
            is_raw_html=raw_html,
            style_overrides=style_overrides,
            template_html_override=template_html_override,
        )
        if not raw_html:
            html = self.assets.inject_code_highlight(
                html, str(metadata.get("scene", ""))
            )
        if self.config.boolean("enable_math", True) and contains_math(content):
            html = self.assets.inject_math(html)
        if template_name != "paper":
            background = self.assets.background_data_url()
            if background:
                html = self.assets.inject_background(html, background)
        return template_name, metadata, html, trusted
