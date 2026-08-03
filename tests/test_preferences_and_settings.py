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

    payload = json.loads(plugin.preferences.path.read_text(encoding="utf-8"))
    key = plugin.actions.preference_key(event)
    assert layout_results[0].payload.endswith("auto")
    assert payload["schema_version"] == 1
    assert payload["entries"][key] == {"layout": "auto", "template": "novel"}

    plugin.preferences.entries = {}
    plugin.templates.user_defaults = {}
    plugin.preferences.load()
    assert plugin.actions.event_template(event) == "novel"
    assert plugin.actions.event_layout(event) == "auto"


def test_corrupt_preferences_fall_back_without_blocking(plugin):
    Path(plugin.preferences.path).write_text("{broken", encoding="utf-8")

    plugin.preferences.load()

    assert plugin.preferences.entries == {}


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

    assert plugin.actions.event_layout(first) == "auto"
    assert plugin.actions.event_layout(second) == "single"


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
