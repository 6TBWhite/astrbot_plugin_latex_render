"""Business logic for chat commands, LLM tools, and request hooks."""

from __future__ import annotations

import re

from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.core.agent.message import TextPart

from ..config import RenderConfig, normalize_layout
from ..preferences import PreferenceStore
from ..rendering.models import RenderFailure, RenderResult
from ..rendering.pipeline import RenderPipeline
from ..template_system.manager import TemplateManager
from ..template_system.service import TemplateService
from .diagnostics import DiagnosticsService
from .hidden_context import HiddenContextBuffer


class RenderActions:
    def __init__(
        self,
        config: RenderConfig,
        preferences: PreferenceStore,
        templates: TemplateService,
        pipeline: RenderPipeline,
        diagnostics: DiagnosticsService,
        hidden_context: HiddenContextBuffer,
    ):
        self.config = config
        self.preferences = preferences
        self.templates = templates
        self.pipeline = pipeline
        self.diagnostics = diagnostics
        self.hidden_context = hidden_context

    @staticmethod
    def user_id(event) -> str:
        try:
            if hasattr(event, "get_sender_id") and callable(event.get_sender_id):
                return str(event.get_sender_id())
            if hasattr(event, "sender") and hasattr(event.sender, "user_id"):
                return str(event.sender.user_id)
            return str(event.unified_msg_origin)
        except Exception:
            return "default_user"

    @staticmethod
    def session_key(event) -> str:
        try:
            return str(event.unified_msg_origin)
        except Exception:
            return ""

    def preference_key(self, event) -> str:
        return f"{self.session_key(event) or 'unknown-session'}|sender:{self.user_id(event)}"

    def event_preference(self, event) -> dict[str, str]:
        return self.preferences.get(self.preference_key(event))

    def event_template(self, event) -> str:
        preference = self.event_preference(event)
        template = str(preference.get("template", "") or "").strip()
        if template and self.templates.has(template):
            return template
        if template:
            preference.pop("template", None)
            if not preference:
                self.preferences.entries.pop(self.preference_key(event), None)
            logger.warning(f"[HTML渲染] 已清理失效的持久化模板偏好: {template}")
            self.preferences.save()
        return self.templates.default(self.user_id(event))

    def event_layout(self, event) -> str:
        layout = normalize_layout(self.event_preference(event).get("layout", ""))
        return layout if layout in {"auto", "single"} else self.config.default_layout

    def agent_current_template(self, event) -> str:
        available = self.templates.available()
        if not available:
            return ""
        try:
            current = self.event_template(event)
        except Exception as exc:
            logger.warning(f"[HTML渲染] 解析 Agent 当前模板失败: {exc}")
            return available[0]
        return current if current in available else available[0]

    @staticmethod
    def extract_images(rendered) -> list:
        if isinstance(rendered, RenderResult):
            return list(rendered.images)
        if isinstance(rendered, list):
            return list(rendered)
        return [rendered] if rendered is not None else []

    @staticmethod
    def extract_warnings(rendered) -> list[str]:
        return list(rendered.warnings) if isinstance(rendered, RenderResult) else []

    @staticmethod
    def _arguments(event, limit: int = 1) -> list[str]:
        message = re.sub(r"\[At:\d+\]\s*", "", event.message_str.strip()).strip()
        return message.split(None, limit)

    def _resolve_template_argument(self, argument: str) -> str | None:
        self.templates.manager.update_template_id_map()
        try:
            selected = self.templates.manager.template_id_map.get(int(argument))
        except ValueError:
            selected = None
        if selected:
            return selected
        return argument if argument in self.templates.available() else None

    async def cmd_test_render(self, event):
        parts = self._arguments(event)
        text = parts[1].strip() if len(parts) > 1 else ""
        user_id = self.user_id(event)
        if not text:
            try:
                template = self.event_template(event)
            except Exception as exc:
                yield event.plain_result(f"渲染失败：{exc}")
                return
            text = TemplateManager.get_default_test_content(template)
        elif text.lower() == "gif":
            text = TemplateManager.get_gif_test_content()
            logger.info("[HTML渲染] 使用 GIF 弹幕测试内容")
        try:
            template = self.event_template(event)
            rendered = await self.pipeline.render_for_layout(
                text, template, user_id, False, self.event_layout(event)
            )
        except Exception as exc:
            yield event.plain_result(self.pipeline.format_failure(exc))
            return
        images = self.extract_images(rendered)
        if not images:
            yield event.plain_result("❌ 渲染失败：浏览器未生成图片")
            return
        yield event.chain_result(images)
        self.hidden_context.record(event, text)

    async def cmd_switch_template(self, event):
        parts = self._arguments(event)
        argument = parts[1].strip() if len(parts) > 1 else ""
        user_id = self.user_id(event)
        try:
            current = self.event_template(event)
        except Exception:
            current = "未设置"
        available = self.templates.available()
        if not available:
            yield event.plain_result(
                "渲染失败：未找到任何模板文件，请先在 "
                f"{self.templates.manager.TEMPLATE_DIR} 中放入至少一个 .html 模板"
            )
            return
        if not argument:
            yield event.plain_result(
                "🔄 切换渲染模板\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "用法: /切换 <模板名或ID>\n"
                f"当前模板: {current}\n\n"
                "示例:\n  /切换 <模板名>\n  /切换 1\n\n"
                "使用 /查看 查看可用模板列表"
            )
            return
        template = self._resolve_template_argument(argument)
        if not template:
            yield event.plain_result(
                f"❌ 未找到模板: {argument}\n\n请使用 /查看 查看可用模板列表"
            )
            return
        self.templates.set_user_default(user_id, template)
        self.preferences.update(self.preference_key(event), template=template)
        logger.info(f"[HTML渲染] 用户 {user_id} 切换默认模板: {current} -> {template}")
        yield event.plain_result(f"✅ 已切换默认模板为: {template}")

    async def cmd_probe_gif(self, event):
        yield event.plain_result("🔍 开始 GIF 渲染探针，请稍候...")
        try:
            yield event.chain_result(await self.diagnostics.gif_probe())
        except Exception as exc:
            logger.exception(f"[探针] 失败: {exc}")
            yield event.plain_result(f"❌ 探针失败: {exc}")

    async def cmd_preview_template(self, event):
        parts = self._arguments(event, 2)
        argument = parts[1].strip() if len(parts) > 1 else ""
        text = parts[2].strip() if len(parts) > 2 else ""
        if not argument:
            yield event.plain_result(
                "📖 用法: /预览模板 <模板名或ID> [文本]\n"
                "示例: /预览模板 <模板名> 晚风穿过旧街，灯火一盏盏亮起来。"
            )
            return
        if not self.templates.available():
            yield event.plain_result(
                "渲染失败：未找到任何模板文件，请先在 "
                f"{self.templates.manager.TEMPLATE_DIR} 中放入至少一个 .html 模板"
            )
            return
        template = self._resolve_template_argument(argument)
        if not template:
            yield event.plain_result(f"❌ 未找到模板: {argument}")
            return
        if not text:
            text = TemplateManager.get_default_test_content(template)
        try:
            rendered = await self.pipeline.render_for_layout(
                text,
                template,
                self.user_id(event),
                False,
                self.event_layout(event),
            )
        except Exception as exc:
            yield event.plain_result(self.pipeline.format_failure(exc))
            return
        images = self.extract_images(rendered)
        if not images:
            yield event.plain_result("❌ 模板预览失败，请检查日志")
            return
        yield event.chain_result([Plain(f"🖼️ 模板预览: {template}"), *images])
        self.hidden_context.record(event, text)

    async def cmd_list_templates(self, event):
        available = self.templates.available()
        if not available:
            yield event.plain_result("❌ 当前没有可用的模板")
            return
        self.templates.manager.update_template_id_map()
        try:
            current = self.event_template(event)
        except Exception:
            current = "未设置"
        lines = ["📋 可用模板列表", "━━━━━━━━━━━━━━━━━━", ""]
        for index in sorted(self.templates.manager.template_id_map):
            name = self.templates.manager.template_id_map[index]
            marker = " ← 当前" if name == current else ""
            metadata = self.templates.manager.get_template_metadata(name)
            display_name = str(metadata.get("display_name", "") or "").strip()
            suffix = (
                f" — {display_name}" if display_name and display_name != name else ""
            )
            lines.append(f"  {index}. {name}{marker}{suffix}")
        lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━━━",
                "使用方法:",
                "  /切换 <ID或名称>      切换默认模板",
                "  /测试 <文本>          测试渲染效果",
                "  /预览模板 <ID或名称> [文本]  临时预览指定模板",
            ]
        )
        yield event.plain_result("\n".join(lines))

    async def cmd_render_settings(self, event):
        parts = self._arguments(event, 2)
        preference = self.event_preference(event)
        if len(parts) == 1:
            yield event.plain_result(
                "🧾 当前渲染设置\n"
                f"模板：{self.event_template(event)}\n"
                f"布局：{self.event_layout(event)}\n"
                f"主题：{str(preference.get('theme', 'default') or 'default')}\n\n"
                "修改布局：/渲染设置 布局 auto|single\n"
                "模板仍使用：/切换 <模板名或ID>"
            )
            return
        if len(parts) != 3 or parts[1].lower() not in {"布局", "layout"}:
            yield event.plain_result("用法：/渲染设置 布局 auto|single")
            return
        layout = normalize_layout(parts[2])
        if layout not in {"auto", "single"}:
            yield event.plain_result("❌ 布局仅支持 auto、single")
            return
        self.preferences.update(self.preference_key(event), layout=layout)
        yield event.plain_result(f"✅ 当前会话的渲染布局已设为: {layout}")

    async def cmd_render_reset(self, event):
        removed = self.preferences.reset(self.preference_key(event))
        self.templates.user_defaults.pop(self.user_id(event), None)
        if removed:
            yield event.plain_result("✅ 已清除当前会话的渲染偏好")
        else:
            yield event.plain_result("ℹ️ 当前会话没有已保存的渲染偏好")

    async def cmd_render_status(self, event):
        yield event.plain_result(self.diagnostics.chat_status())

    async def render_to_image(
        self,
        event,
        content: str = "",
        template: str = "",
        layout: str = "",
    ):
        if not content or not content.strip():
            yield "⚠️ 内容不能为空，请提供需要渲染的 Markdown 文本。"
            return
        selected = (
            template.strip()
            if template and template.strip()
            else self.event_template(event)
        )
        effective_layout = normalize_layout(
            layout if layout and layout.strip() else self.event_layout(event)
        )
        if effective_layout not in {"auto", "single"}:
            yield "⚠️ layout 仅支持 auto 或 single。"
            return
        try:
            rendered = await self.pipeline.render_for_layout(
                content,
                selected,
                self.user_id(event),
                False,
                effective_layout,
            )
        except Exception as exc:
            logger.error(f"[HTML渲染] latex_render_to_image 工具渲染失败: {exc}")
            yield self.pipeline.format_failure(exc)
            return
        images = self.extract_images(rendered)
        warnings = self.extract_warnings(rendered)
        if not images:
            yield "渲染失败：浏览器未生成图片。"
            return
        try:
            await self._send_images(event, images)
        except Exception as exc:
            logger.error(f"[HTML渲染] 图片已生成但发送失败: {exc}")
            yield self._send_failure_message(exc, len(images))
            return
        self.hidden_context.record(event, content)
        yield self._send_success_message(len(images), warnings)

    @staticmethod
    async def _send_images(event, images: list) -> None:
        if len(images) == 1:
            await event.send(event.chain_result(images))
            return
        for page_number, image in enumerate(images, start=1):
            try:
                await event.send(event.chain_result([image]))
            except Exception as exc:
                raise RenderFailure(
                    "send_failed",
                    f"第 {page_number}/{len(images)} 页发送失败；"
                    f"此前已发送 {page_number - 1} 页",
                ) from exc

    @staticmethod
    def _send_failure_message(exc: Exception, image_count: int) -> str:
        if isinstance(exc, RenderFailure) and exc.code == "send_failed":
            return exc.message
        if image_count > 1:
            return (
                f"共生成 {image_count} 页，但整组图片发送失败，"
                "请检查消息平台连接后重试。"
            )
        return "图片已生成，但发送失败，请检查消息平台连接后重试。"

    @staticmethod
    def _send_success_message(image_count: int, warnings: list[str]) -> str:
        if image_count == 1 and not warnings:
            return "图片已渲染并发送给用户。可对图片内容进行简要解说。"
        warning_text = f"；提示：{'；'.join(warnings)}" if warnings else ""
        return (
            f"内容已渲染为 {image_count} 页并发送给用户{warning_text}。"
            "可对图片内容进行简要解说。"
        )

    async def template_guide(self, event, template: str = ""):
        yield self.templates.guidance(
            current_template=self.agent_current_template(event),
            template=template,
        )

    async def on_llm_request(self, event, request) -> None:
        if self.config.boolean("inject_template_prompts"):
            guidance = self.templates.guidance(
                current_template=self.agent_current_template(event),
                compact=True,
            )
            request.extra_user_content_parts.append(
                TextPart(
                    text=(
                        "<render_template_context>\n"
                        "仅在调用 latex_render_to_image 时参考：\n"
                        f"{guidance}\n"
                        "</render_template_context>"
                    )
                ).mark_as_temp()
            )
            logger.info("[HTML渲染] 已注入精简模板提示")
        self.hidden_context.inject(event, request)
