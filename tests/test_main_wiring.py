import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


def test_initialize_uses_declared_service_order(plugin) -> None:
    calls: list[str] = []
    plugin.preferences.load = Mock(side_effect=lambda: calls.append("preferences"))
    plugin.template_mgr.load_templates = AsyncMock(
        side_effect=lambda: calls.append("templates")
    )
    plugin.templates.refresh_schema_options = Mock()
    plugin.templates.require_available = Mock(return_value=["classic"])
    plugin.template_mgr.update_template_id_map = Mock()
    plugin.pipeline.cleanup_cache = Mock()
    plugin.browser.configure = Mock(side_effect=lambda: calls.append("browser-config"))
    plugin.browser.start = AsyncMock(side_effect=lambda: calls.append("browser-start"))
    plugin.webui.register = Mock(side_effect=lambda: calls.append("webui"))

    asyncio.run(plugin.initialize())

    assert calls == [
        "preferences",
        "templates",
        "browser-config",
        "browser-start",
        "webui",
    ]


def test_terminate_persists_preferences_and_stops_browser(plugin) -> None:
    plugin.preferences.save = Mock()
    plugin.browser.stop = AsyncMock()

    asyncio.run(plugin.terminate())

    plugin.preferences.save.assert_called_once_with()
    plugin.browser.stop.assert_awaited_once_with()


def test_framework_command_is_a_thin_async_delegate(
    plugin, fake_event_type, collect_results
) -> None:
    event = fake_event_type("/测试 content")

    async def delegated(received_event):
        assert received_event is event
        yield received_event.plain_result("delegated")

    plugin.actions = SimpleNamespace(cmd_test_render=delegated)

    results = asyncio.run(collect_results(plugin.cmd_test_render(event)))

    assert [result.payload for result in results] == ["delegated"]
