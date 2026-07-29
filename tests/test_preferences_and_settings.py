import asyncio
import json
from pathlib import Path


def test_template_and_layout_preferences_survive_reload(
    plugin, fake_event_type, collect_results
):
    event = fake_event_type("/切换 novel")
    asyncio.run(collect_results(plugin.cmd_switch_template(event)))
    event.message_str = "/渲染设置 布局 paged"
    layout_results = asyncio.run(collect_results(plugin.cmd_render_settings(event)))

    payload = json.loads(Path(plugin.PREFERENCES_PATH).read_text(encoding="utf-8"))
    key = plugin._get_preference_key(event)
    assert layout_results[0].payload.endswith("auto")
    assert payload["schema_version"] == 1
    assert payload["entries"][key] == {"layout": "auto", "template": "novel"}

    plugin.user_preferences = {}
    plugin.user_default_template = {}
    plugin._load_preferences()
    assert plugin._get_event_template(event) == "novel"
    assert plugin._get_event_layout(event) == "auto"


def test_corrupt_preferences_fall_back_without_blocking(plugin):
    Path(plugin.PREFERENCES_PATH).write_text("{broken", encoding="utf-8")

    plugin._load_preferences()

    assert plugin.user_preferences == {}


def test_render_reset_removes_only_current_conversation(
    plugin, fake_event_type, collect_results
):
    first = fake_event_type(
        "/渲染设置 布局 paged",
        unified_msg_origin="platform:message_type:first",
    )
    second = fake_event_type(
        "/渲染设置 布局 single",
        unified_msg_origin="platform:message_type:second",
    )
    asyncio.run(collect_results(plugin.cmd_render_settings(first)))
    asyncio.run(collect_results(plugin.cmd_render_settings(second)))

    first.message_str = "/渲染重置"
    asyncio.run(collect_results(plugin.cmd_render_reset(first)))

    assert plugin._get_event_layout(first) == "auto"
    assert plugin._get_event_layout(second) == "single"


def test_status_does_not_expose_absolute_paths(
    plugin, fake_event_type, collect_results
):
    results = asyncio.run(
        collect_results(plugin.cmd_render_status(fake_event_type("/渲染状态")))
    )
    text = results[0].payload

    assert "LaTeX Render 状态" in text
    assert plugin.DATA_DIR not in text
    assert "运行 0 / 排队 0" in text
