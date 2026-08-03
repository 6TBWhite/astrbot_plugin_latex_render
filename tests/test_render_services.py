import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_latex_render_under_test.config import RenderConfig
from astrbot_plugin_latex_render_under_test.rendering.assets import HtmlAssets
from astrbot_plugin_latex_render_under_test.rendering.document import (
    HtmlDocumentBuilder,
)
from astrbot_plugin_latex_render_under_test.rendering.models import (
    BrowserRenderResult,
    RenderFailure,
)
from astrbot_plugin_latex_render_under_test.rendering.pipeline import RenderPipeline
from astrbot_plugin_latex_render_under_test.rendering.renderer import RenderOptions
from astrbot_plugin_latex_render_under_test.template_system.manager import (
    TemplateManager,
)
from astrbot_plugin_latex_render_under_test.template_system.service import (
    TemplateService,
)


def _services(tmp_path: Path, config_values: dict | None = None):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "classic.html").write_text(
        "<html><head></head><body><main>{{content}}</main></body></html>",
        encoding="utf-8",
    )
    manager = TemplateManager(str(template_dir))
    config = RenderConfig(
        {
            "enable_markdown": True,
            "enable_math": True,
            "enable_code_highlight": False,
            **(config_values or {}),
        }
    )
    templates = TemplateService(manager, config, str(tmp_path))
    assets = HtmlAssets(config, templates, str(tmp_path))
    documents = HtmlDocumentBuilder(config, templates, assets)
    pipeline = RenderPipeline(config, documents, str(tmp_path / "cache"))
    pipeline.schedule_delete = lambda *paths: None
    return templates, assets, documents, pipeline


def test_template_service_selects_and_injects_typed_style(tmp_path) -> None:
    templates, _, _, _ = _services(
        tmp_path, {"classic_font_size": 25, "default_template": "classic"}
    )

    assert templates.select("content") == "classic"
    rendered = templates.apply("**bold**", "classic")

    assert "<strong>bold</strong>" in rendered
    assert "--classic-font-size: 25px" in rendered


def test_document_builder_adds_math_assets_only_when_needed(tmp_path) -> None:
    _, assets, documents, _ = _services(tmp_path)
    assets.mathjax_source = "window.MathJaxLoaded = true;"

    _, _, math_html, _ = documents.build("公式 $x^2$", "classic", None, None, None)
    _, _, plain_html, _ = documents.build("普通文本", "classic", None, None, None)

    assert "data-astrbot-mathjax-loader" in math_html
    assert "data-astrbot-mathjax-loader" not in plain_html


def test_pipeline_builds_compatible_layout_and_fixed_page_options(tmp_path) -> None:
    _, _, _, pipeline = _services(tmp_path, {"default_layout": "paged"})

    options = pipeline.build_options(
        "<html></html>",
        {
            "scene": "paper",
            "preferred_width": 794,
            "fixed_page": {"height": 1123, "top_margin": 76},
        },
        False,
        None,
        {"paper_margin_y": 200},
        False,
    )

    assert options.layout == "auto"
    assert options.width == 794
    assert options.fixed_page_size["top_margin"] == 180
    assert options.fixed_page_size["bottom_margin"] == 180


def test_pipeline_retries_only_browser_failures(tmp_path, monkeypatch) -> None:
    _, _, _, pipeline = _services(tmp_path)
    renderer = AsyncMock(
        side_effect=[
            BrowserRenderResult(False, error_code="browser_error"),
            BrowserRenderResult(True, paths=["render.jpg"]),
        ]
    )
    monkeypatch.setattr(
        "astrbot_plugin_latex_render_under_test.rendering.pipeline.html_to_image_playwright",
        renderer,
    )

    result = asyncio.run(
        pipeline.run_browser(
            RenderOptions(html_content="<p>x</p>", output_image_path="render.jpg")
        )
    )

    assert result.success is True
    assert renderer.await_count == 2


def test_pipeline_rejects_oversized_input_before_browser(tmp_path) -> None:
    _, _, _, pipeline = _services(tmp_path, {"max_input_chars": 100})

    with pytest.raises(RenderFailure, match="超过上限") as error:
        asyncio.run(pipeline.render("x" * 101, "classic"))

    assert error.value.code == "resource_limit"
