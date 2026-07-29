import asyncio
import hashlib
import os
from pathlib import Path

import pytest
from PIL import Image as PILImage, ImageStat


pytestmark = pytest.mark.skipif(
    os.environ.get("ASTRBOT_LATEX_RENDER_INTEGRATION") != "1",
    reason="设置 ASTRBOT_LATEX_RENDER_INTEGRATION=1 后运行真实 Chromium 测试",
)


def test_real_chromium_covers_user_command_and_agent_tool(
    plugin, plugin_main, fake_event_type, collect_results
) -> None:
    command_content = (
        "# 渲染验收\n\n| 项目 | 内容 |\n| --- | --- |\n| 用户命令 | $a^2+b^2=c^2$ |"
    )
    agent_content = "## Agent 工具验收\n\n$$\\int_0^1 x^2\\,dx=\\frac{1}{3}$$"
    command_event = fake_event_type(f"/测试 {command_content}")
    agent_event = fake_event_type()
    probe_event = fake_event_type("/探针gif")

    async def exercise_entrypoints():
        try:
            await plugin_main.init_browser()
            command_results = await collect_results(
                plugin.cmd_test_render(command_event)
            )
            agent_results = await collect_results(
                plugin.render_to_image_tool(
                    agent_event,
                    content=agent_content,
                    template="classic",
                )
            )
            probe_results = await collect_results(plugin.cmd_probe_gif(probe_event))
            return command_results, agent_results, probe_results
        finally:
            await plugin_main.close_browser()

    command_results, agent_results, probe_results = asyncio.run(exercise_entrypoints())

    assert len(command_results) == 1
    assert command_results[0].kind == "chain"
    assert agent_results == ["图片已渲染并发送给用户。可对图片内容进行简要解说。"]
    assert len(agent_event.sent) == 1
    assert len(probe_results) == 2
    assert probe_results[0].kind == "plain"
    assert probe_results[1].kind == "chain"
    assert "检测到 1 个动画元素" in probe_results[1].payload[0].text
    assert len(probe_results[1].payload[1:]) == 3

    command_image = command_results[0].payload[0]
    agent_image = agent_event.sent[0].payload[0]
    probe_images = probe_results[1].payload[1:]

    expected_images = [
        (command_image, "JPEG"),
        (agent_image, "JPEG"),
        *((image, "PNG") for image in probe_images),
    ]
    for image, expected_format in expected_images:
        output_path = Path(image.path)
        assert output_path.is_file()
        assert output_path.stat().st_size > 10_000
        with PILImage.open(output_path) as rendered:
            assert rendered.format == expected_format
            assert rendered.width == 1200
            assert rendered.height >= 300
            extrema = ImageStat.Stat(rendered.convert("RGB")).extrema
            assert any(low < high for low, high in extrema)

    probe_hashes = {
        hashlib.sha256(Path(image.path).read_bytes()).hexdigest()
        for image in probe_images
    }
    assert len(probe_hashes) >= 2


def test_real_chromium_paginates_to_identical_a4_pages(plugin, plugin_main) -> None:
    paragraphs = "\n\n".join(
        f"## 第 {index} 节\n\n"
        "这是一段用于验证 A4 固定纸张分页的正文。"
        "页面必须保持相同尺寸，同时尽量在 Markdown 语义块边界换页。"
        for index in range(1, 24)
    )

    async def render_paper():
        try:
            await plugin_main.init_browser()
            return await plugin._render_content(
                f"# 固定 A4 页面测试\n\n{paragraphs}",
                "paper",
                "user-1",
                False,
            )
        finally:
            await plugin_main.close_browser()

    result = asyncio.run(render_paper())

    assert result.template == "paper"
    assert 2 <= len(result.images) <= 8
    for image in result.images:
        with PILImage.open(image.path) as rendered:
            assert rendered.format == "JPEG"
            assert rendered.size == (1588, 2246)
            assert rendered.getpixel((0, 0)) == (255, 255, 255)


def test_real_chromium_renders_distinct_aurora_custom_starter(
    plugin,
    plugin_main,
    tmp_path,
) -> None:
    plugin.template_mgr = plugin_main.TemplateManager(
        str(Path(__file__).resolve().parents[1] / "templates"),
        str(tmp_path / "custom_templates"),
    )
    metadata = plugin.template_mgr.ensure_custom_slot()
    plugin.template_mgr.update_template_id_map()

    async def render_custom():
        try:
            await plugin_main.init_browser()
            return await plugin._render_content(
                "# Aurora 灵感\n\n"
                "> 这是一张独立的深色 Custom 模板。\n\n"
                "- 摘要\n- 公式 $a^2+b^2=c^2$\n\n"
                "```python\nprint('custom')\n```",
                "custom",
                "user-1",
                False,
            )
        finally:
            await plugin_main.close_browser()

    result = asyncio.run(render_custom())

    assert metadata["display_name"] == "Aurora 灵感卡"
    assert result.template == "custom"
    assert len(result.images) == 1
    with PILImage.open(result.images[0].path) as rendered:
        assert rendered.format == "JPEG"
        assert rendered.width == 1200
        assert rendered.height >= 500
        mean = ImageStat.Stat(rendered.convert("RGB")).mean
        assert sum(mean) / len(mean) < 110
