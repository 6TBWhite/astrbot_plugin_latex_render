"""AstrBot composition root and decorated framework adapters."""

from __future__ import annotations

import asyncio
import os

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.star.star_tools import StarTools

from . import __version__
from .application.actions import RenderActions
from .application.diagnostics import DiagnosticsService
from .application.hidden_context import HiddenContextBuffer
from .application.webui import WebUIController
from .config import RenderConfig
from .preferences import PreferenceStore
from .rendering.assets import HtmlAssets
from .rendering.browser_runtime import BrowserRuntime
from .rendering.document import HtmlDocumentBuilder
from .rendering.pipeline import RenderPipeline
from .template_system.manager import TemplateManager
from .template_system.service import TemplateService

_PLUGIN_NAME = "astrbot_plugin_latex_render"
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


class LatexRenderPlugin(Star):
    """Compose rendering services and expose AstrBot framework entrypoints."""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self.DATA_DIR = os.path.normpath(StarTools.get_data_dir(_PLUGIN_NAME))
        self.IMAGE_CACHE_DIR = os.path.join(self.DATA_DIR, "latex_cache")
        self._compose_services()

    def _compose_services(self) -> None:
        """Build the dependency graph without starting external resources."""

        custom_templates = os.path.join(self.DATA_DIR, "custom_templates")
        self.template_mgr = TemplateManager(
            os.path.join(_PLUGIN_DIR, "templates"), custom_templates
        )
        try:
            self.template_mgr.ensure_custom_slot()
        except Exception as exc:
            logger.warning(f"[HTML渲染] 初始化 Custom 模板失败: {exc}")

        self.render_config = RenderConfig(self.config)
        self.preferences = PreferenceStore(
            os.path.join(self.DATA_DIR, "preferences.json")
        )
        self.templates = TemplateService(
            self.template_mgr, self.render_config, _PLUGIN_DIR
        )
        self.assets = HtmlAssets(self.render_config, self.templates, _PLUGIN_DIR)
        self.documents = HtmlDocumentBuilder(
            self.render_config, self.templates, self.assets
        )
        self.pipeline = RenderPipeline(
            self.render_config, self.documents, self.IMAGE_CACHE_DIR
        )
        self.browser = BrowserRuntime(self.DATA_DIR)
        self.diagnostics = DiagnosticsService(
            self.pipeline, self.templates, _PLUGIN_DIR, self.IMAGE_CACHE_DIR
        )
        self.hidden_context = HiddenContextBuffer(self.render_config)
        self.actions = RenderActions(
            self.render_config,
            self.preferences,
            self.templates,
            self.pipeline,
            self.diagnostics,
            self.hidden_context,
        )
        self.webui = WebUIController(
            self.context,
            self.actions,
            _PLUGIN_NAME,
            __version__,
        )

    async def initialize(self):
        try:
            os.makedirs(self.IMAGE_CACHE_DIR, exist_ok=True)
            self.preferences.load()
            await self.template_mgr.load_templates()
            self.templates.refresh_schema_options()
            self.templates.require_available()
            self.template_mgr.update_template_id_map()
            self.pipeline.cleanup_cache()
            self.browser.configure()
            await self.browser.start()
            self.webui.register()
            if self.render_config.boolean("enable_hidden_ctx_buffer"):
                logger.warning(
                    "[实验性] 隐藏上下文缓冲区已开启。此功能仅对超长推导链（>20轮）"
                    "调试有用，普通会话建议关闭以节省上下文空间"
                )
            logger.info("HTML 渲染插件初始化完成")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"HTML 渲染插件初始化失败: {exc}")
            raise RuntimeError(f"HTML 渲染插件初始化失败: {exc}") from exc

    async def terminate(self):
        self.preferences.save()
        await self.browser.stop()
        logger.info("HTML 渲染插件已停止")

    @filter.command("测试", alias={"test"})
    async def cmd_test_render(self, event: AstrMessageEvent):
        """测试当前模板的 Markdown / LaTeX 渲染效果。"""
        async for result in self.actions.cmd_test_render(event):
            yield result

    @filter.command("切换", alias={"switch"})
    async def cmd_switch_template(self, event: AstrMessageEvent):
        """切换当前用户的默认渲染模板。"""
        async for result in self.actions.cmd_switch_template(event):
            yield result

    @filter.command("探针gif", alias={"probegif"})
    async def cmd_probe_gif(self, event: AstrMessageEvent):
        """诊断 GIF 渲染问题：截取多帧并保存为独立图片"""
        async for result in self.actions.cmd_probe_gif(event):
            yield result

    @filter.command("预览模板", alias={"previewtpl", "tplpreview"})
    async def cmd_preview_template(self, event: AstrMessageEvent):
        """临时预览指定模板，不修改默认模板。"""
        async for result in self.actions.cmd_preview_template(event):
            yield result

    @filter.command("查看", alias={"templates"})
    async def cmd_list_templates(self, event: AstrMessageEvent):
        """查看可用模板及当前默认模板。"""
        async for result in self.actions.cmd_list_templates(event):
            yield result

    @filter.command("渲染设置", alias={"rendersettings"})
    async def cmd_render_settings(self, event: AstrMessageEvent):
        """查看或修改当前会话用户的渲染布局偏好。"""
        async for result in self.actions.cmd_render_settings(event):
            yield result

    @filter.command("渲染重置", alias={"renderreset"})
    async def cmd_render_reset(self, event: AstrMessageEvent):
        """清除当前会话用户的持久化渲染偏好。"""
        async for result in self.actions.cmd_render_reset(event):
            yield result

    @filter.command("渲染状态", alias={"renderstatus"})
    async def cmd_render_status(self, event: AstrMessageEvent):
        """报告不含本机路径的安全运行状态。"""
        async for result in self.actions.cmd_render_status(event):
            yield result

    @filter.llm_tool(name="latex_render_to_image")
    async def latex_render_to_image_tool(
        self,
        event: AstrMessageEvent,
        content: str = "",
        template: str = "",
        layout: str = "",
    ):
        """将完整 Markdown、LaTeX、表格和显式语言代码渲染为一张或多张图片，并直接发送给当前用户。

        当用户明确要求图片，或当前任务需要把公式推导、讲解、报告等排版内容以图片交付时调用；不用于文生图。

        Args:
            content(string): 要渲染的完整 Markdown + LaTeX 正文。
            template(string): 可选。通常留空以沿用当前模板；仅在用户明确指定或已经选定模板时填写。
            layout(string): 可选。留空沿用当前会话设置；auto（自动分页）或 single（单张长图）。
        """
        async for result in self.actions.render_to_image(
            event, content, template, layout
        ):
            yield result

    @filter.llm_tool(name="latex_render_template_guide")
    async def latex_render_template_guide_tool(
        self,
        event: AstrMessageEvent,
        template: str = "",
    ):
        """查询 LaTeX Render 插件当前实际可用的模板、会话当前模板及内容写作规范；只返回说明，不渲染或发送图片。

        当用户询问样式、需要选择模板，或准备调用 latex_render_to_image 但不确定 template 时调用。

        Args:
            template(string): 可选。留空返回全部模板概览；填写模板名返回该模板的详细说明。
        """
        async for result in self.actions.template_guide(event, template):
            yield result

    @filter.on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, req: ProviderRequest):
        await self.actions.on_llm_request(event, req)
