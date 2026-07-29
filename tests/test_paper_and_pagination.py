import asyncio
import importlib
from pathlib import Path
from unittest.mock import AsyncMock

from PIL import Image as PILImage


def test_semantic_pagination_keeps_short_lead_in_with_formula(plugin_main):
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    blocks = [
        {
            "top": 0,
            "bottom": 360,
            "tag": "p",
            "height": 360,
            "text_length": 300,
            "keep_target": False,
        },
        {
            "top": 380,
            "bottom": 430,
            "tag": "p",
            "height": 50,
            "text_length": 2,
            "keep_target": False,
        },
        {
            "top": 450,
            "bottom": 620,
            "tag": "div",
            "height": 170,
            "text_length": 12,
            "keep_target": True,
        },
        {
            "top": 640,
            "bottom": 780,
            "tag": "p",
            "height": 140,
            "text_length": 80,
            "keep_target": False,
        },
        {
            "top": 800,
            "bottom": 980,
            "tag": "p",
            "height": 180,
            "text_length": 100,
            "keep_target": False,
        },
    ]

    groups = renderer._group_pagination_blocks(blocks)

    assert groups[1] == {"top": 380, "bottom": 620, "breakable": True}

    class FakePage:
        async def evaluate(self, _script):
            return blocks

    slices, hard_breaks = asyncio.run(
        renderer._calculate_page_slices(
            FakePage(),
            full_height=980,
            max_page_height=500,
            max_pages=4,
        )
    )

    assert slices == [(0, 360), (360, 780), (780, 980)]
    assert 430 not in {end for _, end in slices}
    assert hard_breaks == set()


def test_paginated_image_bottom_buffer_matches_edge(plugin_main, tmp_path) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    path = tmp_path / "page.jpg"
    image = PILImage.new("RGB", (120, 200), (31, 72, 52))
    image.paste((245, 241, 230), (12, 0, 108, 200))
    image.save(path, "JPEG", quality=95)

    renderer._append_bottom_buffer(str(path), padding_css=40, scale=2)

    with PILImage.open(path) as buffered:
        assert buffered.size == (120, 280)
        left = buffered.getpixel((4, 260))
        center = buffered.getpixel((60, 260))
        assert left[1] > left[0]
        assert min(center) > 220


def test_paper_template_requests_fixed_a4_canvas(plugin, plugin_main, monkeypatch):
    captured = {}

    async def fake_renderer(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_image_path"]).write_bytes(b"paper-image")
        return True

    monkeypatch.setattr(
        plugin_main, "html_to_image_playwright", AsyncMock(side_effect=fake_renderer)
    )

    result = asyncio.run(
        plugin._render_content(
            "# 课程论文\n\n正文段落。\n\n$$E=mc^2$$",
            "paper",
            "user-1",
            False,
        )
    )

    assert result.template == "paper"
    assert len(result.images) == 1
    assert captured["width"] == 794
    assert captured["layout"] == "auto"
    assert captured["fixed_page_size"] == {
        "width": 794,
        "height": 1123,
        "top_margin": 76,
        "bottom_margin": 76,
        "content_height": 971,
    }


def test_agent_tool_sends_all_rendered_pages(
    plugin, plugin_main, fake_event_type, collect_results
):
    pages = [object(), object(), object()]
    plugin._render_content = AsyncMock(
        return_value=plugin_main.RenderResult(
            images=pages,
            template="classic",
            metrics={"page_count": 3},
        )
    )
    event = fake_event_type()

    results = asyncio.run(
        collect_results(
            plugin.render_to_image_tool(
                event,
                content="\n\n".join(f"段落 {i}" for i in range(100)),
                template="classic",
                layout="paged",
            )
        )
    )

    assert [sent.payload[0] for sent in event.sent] == pages
    assert "3 页" in results[0]
    plugin._render_content.assert_awaited_once_with(
        "\n\n".join(f"段落 {i}" for i in range(100)),
        "classic",
        "user-1",
        False,
    )


def test_agent_tool_reports_exact_failed_page(
    plugin, plugin_main, fake_event_type, collect_results
):
    plugin.config["enable_hidden_ctx_buffer"] = True
    pages = [object(), object(), object()]
    plugin._render_content = AsyncMock(
        return_value=plugin_main.RenderResult(images=pages, template="classic")
    )
    event = fake_event_type()
    event.send = AsyncMock(side_effect=[None, RuntimeError("adapter failed")])

    results = asyncio.run(
        collect_results(
            plugin.render_to_image_tool(
                event,
                content="多页内容",
                template="classic",
                layout="paged",
            )
        )
    )

    assert results == ["第 2/3 页发送失败；此前已发送 1 页"]
    assert plugin._hidden_ctx_buffer == {}


def test_background_discovery_is_limited_to_admin_asset_directory(
    plugin, plugin_main, monkeypatch, tmp_path
):
    background_dir = tmp_path / "assets" / "backgrounds"
    background_dir.mkdir(parents=True)
    PILImage.new("RGB", (10, 10), "white").save(background_dir / "approved.png")
    PILImage.new("RGB", (10, 10), "black").save(tmp_path / "logo.png")
    monkeypatch.setattr(plugin_main, "_PLUGIN_DIR", str(tmp_path))

    assert plugin._get_available_background_images() == [
        "assets/backgrounds/approved.png"
    ]
