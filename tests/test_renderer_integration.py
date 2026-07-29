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
