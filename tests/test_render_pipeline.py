import asyncio
import importlib
from pathlib import Path
from unittest.mock import AsyncMock

from astrbot_plugin_latex_render_under_test.rendering.models import (
    BrowserRenderResult,
    RenderFailure,
)
from astrbot_plugin_latex_render_under_test.rendering.renderer import RenderOptions


def test_page_number_margin_follows_template_footer(plugin) -> None:
    margin_for = plugin.pipeline.page_number_bottom_margin

    assert margin_for({"scene": "knowledge"}) == 24
    assert margin_for({"scene": "custom"}) == 8
    assert margin_for({"scene": "story"}) == 20
    assert margin_for({"scene": "paper"}) == 20


def test_render_pipeline_applies_markdown_mathjax_and_template(
    plugin, plugin_main, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_renderer(options):
        captured.update(options.__dict__)
        Path(options.output_image_path).write_bytes(b"image-placeholder")
        return True

    pipeline_module = importlib.import_module(
        f"{plugin_main.__package__}.rendering.pipeline"
    )
    monkeypatch.setattr(
        pipeline_module,
        "html_to_image_playwright",
        AsyncMock(side_effect=fake_renderer),
    )

    image = asyncio.run(
        plugin.pipeline.render(
            "## 公式表\n\n| 名称 | 公式 |\n| --- | --- |\n| 勾股定理 | $a^2+b^2=c^2$ |",
            "classic",
            "user-1",
            False,
        )
    )

    html = captured["html_content"]
    assert image is not None
    assert "<table>" in html
    assert "astr-math-inline" in html
    assert "astrbot-mathjax-script" in html
    assert "data-astrbot-mathjax-loader" in html
    assert "BUILTIN_PROMPT" not in html
    assert captured["width"] == 600
    assert captured["scale"] == 2
    assert captured["is_gif"] is False
    assert captured["page_number_bottom_margin"] == 24


def test_regular_template_keeps_configured_render_width(
    plugin, plugin_main, monkeypatch
) -> None:
    captured = {}
    plugin.config["render_width"] = 720

    async def fake_renderer(options):
        captured.update(options.__dict__)
        Path(options.output_image_path).write_bytes(b"image-placeholder")
        return True

    pipeline_module = importlib.import_module(
        f"{plugin_main.__package__}.rendering.pipeline"
    )
    monkeypatch.setattr(
        pipeline_module,
        "html_to_image_playwright",
        AsyncMock(side_effect=fake_renderer),
    )

    asyncio.run(plugin.pipeline.render("普通内容", "classic", "user-1", False))

    assert captured["width"] == 720


def test_regular_template_forwards_configured_auto_page_height(
    plugin, plugin_main, monkeypatch
) -> None:
    captured = {}
    plugin.config["max_page_height"] = 3600

    async def fake_renderer(options):
        captured.update(options.__dict__)
        Path(options.output_image_path).write_bytes(b"image-placeholder")
        return True

    pipeline_module = importlib.import_module(
        f"{plugin_main.__package__}.rendering.pipeline"
    )
    monkeypatch.setattr(
        pipeline_module,
        "html_to_image_playwright",
        AsyncMock(side_effect=fake_renderer),
    )

    asyncio.run(plugin.pipeline.render("普通内容", "classic", "user-1", False))

    assert captured["layout"] == "auto"
    assert captured["max_page_height"] == 3600


def test_browser_render_retries_one_browser_failure(
    plugin, plugin_main, monkeypatch
) -> None:
    renderer = AsyncMock(
        side_effect=[
            BrowserRenderResult(
                success=False,
                error_code="browser_error",
                error_message="browser disconnected",
            ),
            BrowserRenderResult(
                success=True,
                paths=["render.jpg"],
            ),
        ]
    )
    pipeline_module = importlib.import_module(
        f"{plugin_main.__package__}.rendering.pipeline"
    )
    monkeypatch.setattr(pipeline_module, "html_to_image_playwright", renderer)
    options = RenderOptions(
        html_content="<p>content</p>", output_image_path="render.jpg"
    )

    result = asyncio.run(plugin.pipeline.run_browser(options))

    assert result.success is True
    assert renderer.await_count == 2


def test_browser_render_does_not_retry_resource_limit(
    plugin, plugin_main, monkeypatch
) -> None:
    renderer = AsyncMock(
        return_value=BrowserRenderResult(
            success=False,
            error_code="resource_limit",
            error_message="too many pages",
        )
    )
    pipeline_module = importlib.import_module(
        f"{plugin_main.__package__}.rendering.pipeline"
    )
    monkeypatch.setattr(pipeline_module, "html_to_image_playwright", renderer)
    options = RenderOptions(
        html_content="<p>content</p>", output_image_path="render.jpg"
    )

    try:
        asyncio.run(plugin.pipeline.run_browser(options))
    except RenderFailure as exc:
        assert exc.code == "resource_limit"
    else:
        raise AssertionError("resource limits must fail without a browser retry")
    assert renderer.await_count == 1
