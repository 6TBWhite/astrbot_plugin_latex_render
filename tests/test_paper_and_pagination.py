import asyncio
import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image as PILImage, ImageChops, ImageStat


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

    assert groups[1] == {
        "top": 380,
        "bottom": 620,
        "breakable": True,
        "block_indexes": [1, 2],
    }

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


def test_pack_into_pages_fills_fixed_height_pages(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    groups = [
        {"top": 0, "bottom": 1000, "breakable": True, "block_indexes": [0]},
        {"top": 1040, "bottom": 2100, "breakable": True, "block_indexes": [1]},
        {"top": 2140, "bottom": 3000, "breakable": True, "block_indexes": [2]},
        {"top": 3040, "bottom": 4500, "breakable": True, "block_indexes": [3]},
        {"top": 4540, "bottom": 5000, "breakable": True, "block_indexes": [4]},
    ]
    pages, hard = renderer._pack_into_pages(groups, page_height=3200, max_pages=4)
    assert pages == [[0, 1, 2], [3, 4]]
    assert hard == set()


def test_pack_into_pages_marks_oversized_group_as_hard(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    groups = [
        {"top": 0, "bottom": 3000, "breakable": True, "block_indexes": [0]},
        {"top": 3040, "bottom": 7000, "breakable": True, "block_indexes": [1]},
        {"top": 7040, "bottom": 8000, "breakable": True, "block_indexes": [2]},
    ]
    pages, hard = renderer._pack_into_pages(groups, page_height=3200, max_pages=5)
    assert pages == [[0], [1], [2]]
    assert hard == {1}


def test_pack_into_pages_raises_when_exceeding_max_pages(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    groups = [
        {
            "top": i * 4000,
            "bottom": i * 4000 + 1000,
            "breakable": True,
            "block_indexes": [i],
        }
        for i in range(4)
    ]
    try:
        renderer._pack_into_pages(groups, page_height=3200, max_pages=2)
    except ValueError as exc:
        assert "分页结果" in str(exc)
    else:
        raise AssertionError("应抛出页数超限异常")


def test_static_layout_uses_fixed_page_content_height(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    options = renderer.RenderOptions(
        html_content="<p>content</p>",
        output_image_path="render.jpg",
        layout="single",
        max_page_height=3200,
        fixed_page_size={"content_height": 971},
    )

    layout, page_height, should_paginate = renderer._resolve_static_layout(
        options, full_height=800
    )

    assert layout == "paged"
    assert page_height == 971
    assert should_paginate is True


def test_static_single_layout_rejects_absolute_height_overflow(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    options = renderer.RenderOptions(
        html_content="<p>content</p>",
        output_image_path="render.jpg",
        layout="single",
        max_page_height=1000,
        max_pages=2,
    )

    with pytest.raises(ValueError, match="单页高度"):
        renderer._resolve_static_layout(options, full_height=2001)


def test_page_output_path_preserves_legacy_second_page_name(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")

    assert renderer._page_output_path("render.jpg", 0) == "render_p0.jpg"
    assert renderer._page_output_path("render.jpg", 1) == "render.jpg"
    assert renderer._page_output_path("render.jpg", 2) == "render_p2.jpg"


def test_page_number_font_size_tracks_render_scale(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")

    assert renderer._page_number_font_size(0) == 14
    assert renderer._page_number_font_size(1) == 14
    assert renderer._page_number_font_size(2) == 28
    assert renderer._page_number_font_size(3) == 42


def test_page_number_position_is_centered_with_scaled_bottom_margin(
    plugin_main,
) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    text_bbox = (0, 4, 100, 24)

    x, y = renderer._page_number_position(
        (1200, 6400), text_bbox, scale=2, bottom_margin=24
    )
    actual_box = (
        x + text_bbox[0],
        y + text_bbox[1],
        x + text_bbox[2],
        y + text_bbox[3],
    )

    assert (actual_box[0] + actual_box[2]) // 2 == 600
    assert 6400 - actual_box[3] == 48
    _, default_y = renderer._page_number_position(
        (1200, 6400), text_bbox, scale=2
    )
    assert 6400 - (default_y + text_bbox[3]) == 40


def test_page_number_color_adapts_to_footer_luminance(plugin_main) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    text_box = (100, 80, 200, 110)
    light_page = PILImage.new("RGB", (300, 140), (245, 245, 240))
    dark_page = PILImage.new("RGB", (300, 140), (38, 48, 43))

    assert renderer._page_number_color(light_page, text_box, 2) == (
        42,
        42,
        42,
        190,
    )
    assert renderer._page_number_color(dark_page, text_box, 2) == (
        246,
        242,
        232,
        220,
    )


def test_page_number_skips_single_page_without_touching_file(
    plugin_main, tmp_path
) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    path = tmp_path / "single.jpg"
    PILImage.new("RGB", (600, 400), (240, 235, 224)).save(
        path, "JPEG", quality=90, optimize=True
    )
    before = path.read_bytes()

    renderer._add_page_number(str(path), 1, 1, scale=2)

    assert path.read_bytes() == before


def test_page_number_preserves_canvas_and_only_changes_footer(
    plugin_main, tmp_path
) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    path = tmp_path / "paged.jpg"
    PILImage.new("RGB", (600, 400), (240, 235, 224)).save(
        path, "JPEG", quality=90, optimize=True
    )
    with PILImage.open(path) as original_source:
        original = original_source.convert("RGB")

    renderer._add_page_number(str(path), 1, 5, scale=2)

    with PILImage.open(path) as rendered_source:
        rendered = rendered_source.convert("RGB")
    assert rendered.size == original.size
    content_diff = ImageChops.difference(
        original.crop((0, 0, 600, 320)), rendered.crop((0, 0, 600, 320))
    )
    assert max(ImageStat.Stat(content_diff).rms) <= 1.0
    footer_diff = ImageChops.difference(
        original.crop((0, 320, 600, 400)), rendered.crop((0, 320, 600, 400))
    )
    assert footer_diff.getbbox() is not None


def test_animation_detection_stops_after_css_strategy_decides(
    plugin_main, monkeypatch
) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    css_clip = {"x": 10, "y": 20, "width": 300, "height": 200}
    css_detector = AsyncMock(return_value=(True, css_clip))
    pixel_detector = AsyncMock()
    monkeypatch.setattr(renderer, "_detect_css_animated_region", css_detector)
    monkeypatch.setattr(renderer, "_detect_pixel_animated_region", pixel_detector)

    result = asyncio.run(
        renderer._detect_animated_region(object(), 2, 600, 800)
    )

    assert result == css_clip
    pixel_detector.assert_not_awaited()


def test_animation_detection_falls_back_to_pixel_strategy(
    plugin_main, monkeypatch
) -> None:
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")
    pixel_clip = {"x": 5, "y": 6, "width": 100, "height": 80}
    monkeypatch.setattr(
        renderer,
        "_detect_css_animated_region",
        AsyncMock(return_value=(False, None)),
    )
    pixel_detector = AsyncMock(return_value=pixel_clip)
    monkeypatch.setattr(renderer, "_detect_pixel_animated_region", pixel_detector)

    result = asyncio.run(
        renderer._detect_animated_region(object(), 2, 600, 800)
    )

    assert result == pixel_clip
    pixel_detector.assert_awaited_once()


def test_paper_template_requests_fixed_a4_canvas(plugin, plugin_main, monkeypatch):
    captured = {}

    async def fake_renderer(options):
        captured.update(options.__dict__)
        Path(options.output_image_path).write_bytes(b"paper-image")
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
    assert captured["page_number_bottom_margin"] == 20
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
            plugin.latex_render_to_image_tool(
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
            plugin.latex_render_to_image_tool(
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
