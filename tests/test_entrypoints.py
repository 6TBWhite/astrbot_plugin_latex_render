import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_test_command_uses_current_user_template(
    plugin, fake_event_type, collect_results
) -> None:
    plugin.user_default_template["user-1"] = "novel"
    rendered_image = object()
    plugin._render_content = AsyncMock(return_value=rendered_image)
    event = fake_event_type("/测试 # 自定义内容")

    results = asyncio.run(collect_results(plugin.cmd_test_render(event)))

    plugin._render_content.assert_awaited_once_with(
        "# 自定义内容", "novel", "user-1", False
    )
    assert len(results) == 1
    assert results[0].kind == "chain"
    assert results[0].payload == [rendered_image]


def test_test_command_without_text_uses_builtin_content(
    plugin, fake_event_type, collect_results
) -> None:
    rendered_image = object()
    plugin._render_content = AsyncMock(return_value=rendered_image)
    event = fake_event_type("/测试")

    asyncio.run(collect_results(plugin.cmd_test_render(event)))

    content, template, user_id, is_gif = plugin._render_content.await_args.args
    assert "# HTML Render Preview" in content
    assert template == "classic"
    assert user_id == "user-1"
    assert is_gif is False


def test_switch_and_list_commands_update_user_default(
    plugin, fake_event_type, collect_results
) -> None:
    switch_event = fake_event_type("/切换 novel")

    switch_results = asyncio.run(
        collect_results(plugin.cmd_switch_template(switch_event))
    )
    list_results = asyncio.run(
        collect_results(plugin.cmd_list_templates(fake_event_type("/查看")))
    )

    assert plugin.user_default_template == {"user-1": "novel"}
    assert "已切换默认模板为: novel" in switch_results[0].payload
    assert "novel ← 当前" in list_results[0].payload


def test_preview_command_renders_selected_template_without_changing_default(
    plugin, fake_event_type, collect_results
) -> None:
    plugin.user_default_template["user-1"] = "classic"
    rendered_image = object()
    plugin._render_content = AsyncMock(return_value=rendered_image)
    event = fake_event_type("/预览模板 novel 雨落在旧街上。")

    results = asyncio.run(collect_results(plugin.cmd_preview_template(event)))

    plugin._render_content.assert_awaited_once_with(
        "雨落在旧街上。", "novel", "user-1", False
    )
    assert plugin.user_default_template == {"user-1": "classic"}
    assert results[0].kind == "chain"
    assert results[0].payload[0].text == "🖼️ 模板预览: novel"
    assert results[0].payload[1] is rendered_image


def test_agent_tool_sends_rendered_image(
    plugin, fake_event_type, collect_results
) -> None:
    rendered_image = object()
    plugin._render_content = AsyncMock(return_value=rendered_image)
    event = fake_event_type()

    results = asyncio.run(
        collect_results(
            plugin.render_to_image_tool(
                event,
                content="## 勾股定理\n\n$a^2+b^2=c^2$",
                template="classic",
            )
        )
    )

    plugin._render_content.assert_awaited_once_with(
        "## 勾股定理\n\n$a^2+b^2=c^2$", "classic", "user-1", False
    )
    assert len(event.sent) == 1
    assert event.sent[0].kind == "chain"
    assert event.sent[0].payload == [rendered_image]
    assert results == ["图片已渲染并发送给用户。可对图片内容进行简要解说。"]


def test_agent_tool_rejects_empty_content_without_sending(
    plugin, fake_event_type, collect_results
) -> None:
    plugin._render_content = AsyncMock()
    event = fake_event_type()

    results = asyncio.run(
        collect_results(plugin.render_to_image_tool(event, content="  "))
    )

    plugin._render_content.assert_not_awaited()
    assert event.sent == []
    assert results == ["⚠️ 内容不能为空，请提供需要渲染的 Markdown 文本。"]


def test_agent_tool_rejects_unknown_template(
    plugin, fake_event_type, collect_results
) -> None:
    event = fake_event_type()

    results = asyncio.run(
        collect_results(
            plugin.render_to_image_tool(
                event,
                content="有效内容",
                template="missing-template",
            )
        )
    )

    assert event.sent == []
    assert len(results) == 1
    assert "模板不存在" in results[0]


def test_agent_tool_handles_message_send_failure_without_recording_context(
    plugin, fake_event_type, collect_results
) -> None:
    plugin.config["enable_hidden_ctx_buffer"] = True
    plugin._render_content = AsyncMock(return_value=object())
    event = fake_event_type()
    event.send = AsyncMock(side_effect=RuntimeError("adapter unavailable"))

    results = asyncio.run(
        collect_results(plugin.render_to_image_tool(event, content="待发送内容"))
    )

    assert results == ["图片已生成，但发送失败，请检查消息平台连接后重试。"]
    assert plugin._hidden_ctx_buffer == {}


def test_hidden_context_only_records_successful_render(
    plugin, fake_event_type, collect_results
) -> None:
    plugin.config["enable_hidden_ctx_buffer"] = True
    event = fake_event_type()
    plugin._render_content = AsyncMock(return_value=None)

    failed_results = asyncio.run(
        collect_results(plugin.render_to_image_tool(event, content="失败内容"))
    )

    assert failed_results == ["渲染失败，请检查内容格式后重试。"]
    assert plugin._hidden_ctx_buffer == {}

    plugin._render_content = AsyncMock(return_value=object())
    asyncio.run(collect_results(plugin.render_to_image_tool(event, content="成功内容")))

    assert [
        item["content"] for item in plugin._hidden_ctx_buffer[event.unified_msg_origin]
    ] == ["成功内容"]


def test_hidden_context_is_injected_per_conversation(plugin, fake_event_type) -> None:
    plugin.config["enable_hidden_ctx_buffer"] = True
    first_event = fake_event_type(
        unified_msg_origin="platform:message_type:session-first"
    )
    second_event = fake_event_type(
        unified_msg_origin="platform:message_type:session-second"
    )
    plugin._push_hidden_ctx(first_event, "仅属于第一个会话")

    first_request = SimpleNamespace(extra_user_content_parts=[])
    second_request = SimpleNamespace(extra_user_content_parts=[])
    asyncio.run(plugin.on_llm_req(first_event, first_request))
    asyncio.run(plugin.on_llm_req(second_event, second_request))

    assert len(first_request.extra_user_content_parts) == 1
    assert "仅属于第一个会话" in first_request.extra_user_content_parts[0].text
    assert second_request.extra_user_content_parts == []
