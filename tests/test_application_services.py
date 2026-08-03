import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from core.actions import RenderActions
from core.config import RenderConfig
from core.diagnostics import DiagnosticsService
from core.hidden_context import HiddenContextBuffer
from core.models import RenderResult, RenderRuntimeSnapshot
from core.preferences import PreferenceStore
from core.webui import WebUIController


class Event:
    unified_msg_origin = "platform:group:one"

    def get_sender_id(self):
        return "user-1"

    def chain_result(self, chain):
        return chain


class Request:
    def __init__(self):
        self.extra_user_content_parts = []


def test_hidden_context_is_session_scoped_and_capped_at_three() -> None:
    buffer = HiddenContextBuffer(RenderConfig({"enable_hidden_ctx_buffer": True}))
    first = Event()
    second = Event()
    second.unified_msg_origin = "platform:group:two"

    for content in ("one", "two", "three", "four"):
        buffer.record(first, content)
    buffer.record(second, "separate")
    request = Request()

    assert buffer.inject(first, request) is True
    text = request.extra_user_content_parts[0].text
    assert "one" not in text
    assert all(value in text for value in ("two", "three", "four"))
    assert "separate" not in text


def test_failed_tool_send_does_not_record_hidden_context(tmp_path) -> None:
    config = RenderConfig({"enable_hidden_ctx_buffer": True})
    hidden = HiddenContextBuffer(config)
    pipeline = SimpleNamespace(
        render_for_layout=AsyncMock(
            return_value=RenderResult(images=[object()], template="classic")
        ),
        format_failure=lambda error: str(error),
    )
    actions = RenderActions(
        config,
        PreferenceStore(tmp_path / "preferences.json"),
        SimpleNamespace(),
        pipeline,
        SimpleNamespace(),
        hidden,
    )
    event = Event()
    event.send = AsyncMock(side_effect=RuntimeError("offline"))

    async def run():
        return [
            item
            async for item in actions.render_to_image(
                event, "content", template="classic", layout="auto"
            )
        ]

    result = asyncio.run(run())

    assert result == ["图片已生成，但发送失败，请检查消息平台连接后重试。"]
    assert hidden._items == {}


def test_diagnostics_payload_and_text_never_expose_absolute_paths(
    tmp_path, monkeypatch
) -> None:
    marker = "private-workspace-marker"
    plugin_dir = tmp_path / marker / "plugin"
    cache_dir = tmp_path / marker / "cache"
    plugin_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    pipeline = SimpleNamespace(snapshot=lambda: RenderRuntimeSnapshot())
    manager = SimpleNamespace(get_custom_templates=lambda: [])
    templates = SimpleNamespace(available=lambda: ["classic"], manager=manager)
    service = DiagnosticsService(pipeline, templates, str(plugin_dir), str(cache_dir))
    monkeypatch.setattr(
        "core.diagnostics.get_renderer_status",
        lambda: {"browser_connected": False, "browser_launching": False},
    )
    monkeypatch.setattr(service, "has_probable_cjk_font", lambda: True)

    combined = (
        json.dumps(service.safe_status(), ensure_ascii=False) + service.chat_status()
    )

    assert marker not in combined
    assert str(tmp_path) not in combined


def test_webui_controller_registers_all_legacy_routes() -> None:
    context = SimpleNamespace(register_web_api=Mock())
    controller = WebUIController(
        context,
        None,
        None,
        None,
        None,
        None,
        None,
        "astrbot_plugin_latex_render",
        "1.0.0",
    )

    controller.register()

    paths = [call.args[0] for call in context.register_web_api.call_args_list]
    assert paths == [
        f"/astrbot_plugin_latex_render/page/{route[0]}"
        for route in WebUIController.ROUTES
    ]
