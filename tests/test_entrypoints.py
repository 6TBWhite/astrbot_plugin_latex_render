import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


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
            plugin.latex_render_to_image_tool(
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
        collect_results(plugin.latex_render_to_image_tool(event, content="  "))
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
            plugin.latex_render_to_image_tool(
                event,
                content="有效内容",
                template="missing-template",
            )
        )
    )

    assert event.sent == []
    assert len(results) == 1
    assert "模板不存在" in results[0]


def test_template_query_lists_live_catalog_without_detailed_prompts(
    plugin, fake_event_type, collect_results
) -> None:
    plugin.user_default_template["user-1"] = "novel"

    results = asyncio.run(
        collect_results(plugin.latex_render_template_guide_tool(fake_event_type()))
    )

    assert len(results) == 1
    catalog = results[0]
    assert "当前模板：novel" in catalog
    assert "classic（Classic 知识卡" in catalog
    assert "novel（Novel 小说页，内置，当前）" in catalog
    assert "paper（Paper A4 论文页" in catalog
    assert "标签：" in catalog
    assert "内容规范：" not in catalog
    assert "<q>" not in catalog
    assert "template 留空以沿用当前模板" in catalog


def test_template_query_returns_builtin_details(
    plugin, fake_event_type, collect_results
) -> None:
    results = asyncio.run(
        collect_results(
            plugin.latex_render_template_guide_tool(
                fake_event_type(),
                template="novel",
            )
        )
    )

    assert len(results) == 1
    detail = results[0]
    assert "模板：novel" in detail
    assert "显示名称：Novel 小说页" in detail
    assert "来源：内置" in detail
    assert "内容规范：" in detail
    assert "<q>对话台词</q>" in detail
    assert 'latex_render_to_image 参数：template="novel"' in detail


def test_template_query_limits_custom_metadata_without_reading_source(
    plugin, fake_event_type, collect_results, monkeypatch
) -> None:
    metadata = {
        "display_name": "D" * 100,
        "description": "第一行\n" + "x" * 300,
        "scene": "custom",
        "source": "custom",
        "tags": [f"标签{i}" for i in range(8)],
    }
    prompt_getter = Mock(return_value="<style>SECRET_TEMPLATE_SOURCE</style>")
    monkeypatch.setattr(plugin, "_get_available_templates", lambda: ["custom"])
    monkeypatch.setattr(plugin, "_get_event_template", lambda event: "custom")
    monkeypatch.setattr(
        plugin.template_mgr,
        "get_template_metadata",
        lambda name: metadata,
    )
    monkeypatch.setattr(
        plugin.template_mgr,
        "extract_builtin_prompt",
        prompt_getter,
    )

    results = asyncio.run(
        collect_results(
            plugin.latex_render_template_guide_tool(
                fake_event_type(),
                template="custom",
            )
        )
    )

    detail = results[0]
    assert "来源：自定义" in detail
    assert "D" * 79 + "…" in detail
    assert "第一行 x" in detail
    assert "标签5" in detail
    assert "标签6" not in detail
    assert "SECRET_TEMPLATE_SOURCE" not in detail
    assert (
        len(next(line for line in detail.splitlines() if line.startswith("用途：")))
        == 243
    )
    prompt_getter.assert_not_called()


def test_template_query_handles_unknown_and_empty_catalog(
    plugin, fake_event_type, collect_results, monkeypatch
) -> None:
    unknown_results = asyncio.run(
        collect_results(
            plugin.latex_render_template_guide_tool(
                fake_event_type(),
                template="missing-template",
            )
        )
    )

    assert "未找到模板：missing-template" in unknown_results[0]
    assert "当前可用模板：classic、novel、paper" in unknown_results[0]

    monkeypatch.setattr(plugin, "_get_available_templates", lambda: [])
    empty_results = asyncio.run(
        collect_results(plugin.latex_render_template_guide_tool(fake_event_type()))
    )

    assert empty_results == ["当前没有可用的渲染模板，请检查插件模板目录。"]


def test_agent_tool_handles_message_send_failure_without_recording_context(
    plugin, fake_event_type, collect_results
) -> None:
    plugin.config["enable_hidden_ctx_buffer"] = True
    plugin._render_content = AsyncMock(return_value=object())
    event = fake_event_type()
    event.send = AsyncMock(side_effect=RuntimeError("adapter unavailable"))

    results = asyncio.run(
        collect_results(plugin.latex_render_to_image_tool(event, content="待发送内容"))
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
        collect_results(plugin.latex_render_to_image_tool(event, content="失败内容"))
    )

    assert failed_results == ["渲染失败：浏览器未生成图片。"]
    assert plugin._hidden_ctx_buffer == {}

    plugin._render_content = AsyncMock(return_value=object())
    asyncio.run(
        collect_results(plugin.latex_render_to_image_tool(event, content="成功内容"))
    )

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


def test_template_prompt_injection_uses_dynamic_compact_catalog(
    plugin, fake_event_type, monkeypatch
) -> None:
    plugin.config["inject_template_prompts"] = True
    monkeypatch.setattr(plugin, "_get_available_templates", lambda: ["dynamic"])
    monkeypatch.setattr(plugin, "_get_event_template", lambda event: "dynamic")
    monkeypatch.setattr(
        plugin.template_mgr,
        "get_template_metadata",
        lambda name: {
            "display_name": "Dynamic",
            "description": "运行时模板说明",
            "source": "custom",
            "tags": ["不会注入"],
        },
    )
    request = SimpleNamespace(extra_user_content_parts=[])

    asyncio.run(plugin.on_llm_req(fake_event_type(), request))

    assert len(request.extra_user_content_parts) == 1
    prompt = request.extra_user_content_parts[0].text
    assert "dynamic（Dynamic，自定义，当前）：运行时模板说明" in prompt
    assert "classic" not in prompt
    assert "标签：" not in prompt
    assert "内容规范：" not in prompt
    assert "仅在调用 latex_render_to_image 时参考" in prompt
    assert "template 留空以沿用当前模板" in prompt
