import asyncio
from pathlib import Path
from unittest.mock import AsyncMock


def test_render_pipeline_applies_markdown_mathjax_and_template(
    plugin, plugin_main, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_renderer(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_image_path"]).write_bytes(b"image-placeholder")
        return True

    monkeypatch.setattr(
        plugin_main, "html_to_image_playwright", AsyncMock(side_effect=fake_renderer)
    )

    image = asyncio.run(
        plugin._render_content(
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


def test_regular_template_keeps_configured_render_width(
    plugin, plugin_main, monkeypatch
) -> None:
    captured = {}
    plugin.config["render_width"] = 720

    async def fake_renderer(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_image_path"]).write_bytes(b"image-placeholder")
        return True

    monkeypatch.setattr(
        plugin_main, "html_to_image_playwright", AsyncMock(side_effect=fake_renderer)
    )

    asyncio.run(plugin._render_content("普通内容", "classic", "user-1", False))

    assert captured["width"] == 720


def test_regular_template_forwards_configured_auto_page_height(
    plugin, plugin_main, monkeypatch
) -> None:
    captured = {}
    plugin.config["max_page_height"] = 3600

    async def fake_renderer(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_image_path"]).write_bytes(b"image-placeholder")
        return True

    monkeypatch.setattr(
        plugin_main, "html_to_image_playwright", AsyncMock(side_effect=fake_renderer)
    )

    asyncio.run(plugin._render_content("普通内容", "classic", "user-1", False))

    assert captured["layout"] == "auto"
    assert captured["max_page_height"] == 3600
