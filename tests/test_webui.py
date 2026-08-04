import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from astrbot_plugin_latex_render_under_test.application import (
    diagnostics as diagnostics_module,
)
from astrbot_plugin_latex_render_under_test.application import webui as webui_module
from astrbot_plugin_latex_render_under_test.rendering.models import RenderResult
from astrbot_plugin_latex_render_under_test.template_system.manager import (
    TemplateManager,
)


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PAGE_PATH = PLUGIN_ROOT / "pages" / "studio" / "index.html"


def test_studio_page_is_self_contained_and_uses_plugin_bridge() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")

    assert "AstrBotPluginPage" in text
    assert 'path("bootstrap")' in text
    assert 'path("config")' in text
    assert 'path("preview")' in text
    assert 'path("template")' in text
    assert 'path("template/save")' in text
    assert "<script src=" not in text
    assert "<link rel=" not in text


def test_studio_page_has_three_accessible_work_areas() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")

    assert 'class="tabs" role="tablist"' in text
    assert 'data-view="config"' in text
    assert 'data-view="gallery"' in text
    assert 'data-view="custom"' in text
    assert 'id="config-view"' in text
    assert 'id="gallery-view"' in text
    assert 'id="custom-view"' in text
    assert "基础设置" in text
    assert "模板画廊" in text
    assert "Custom 编辑" in text
    assert "调整渲染方式、输出质量与安全选项" in text
    assert "function setActiveView" in text
    assert '["ArrowLeft", "ArrowRight"]' in text


def test_gallery_uses_real_debounced_preview_and_style_controls() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")

    assert 'data-style-range="' in text
    assert 'data-style-number="' in text
    assert "collectStyleValues" in text
    assert "scheduleGalleryPreview" in text
    assert "550" in text
    assert "previewGeneration" in text
    assert "generation !== state.previewGeneration" in text
    assert "正在调用 Chromium 排版" in text
    assert "设为默认模板" in text
    assert "当前默认模板" in text
    assert "button.disabled = active" in text
    assert '<option value="auto">auto · 超长时分页</option>' in text
    assert '<option value="single">single · 单张长图</option>' in text
    assert '<option value="paged">' not in text
    assert 'id="edit-custom-template"' in text
    assert "保存排版" in text


def test_basic_settings_use_layered_cards_and_explanatory_tooltips(
    plugin,
) -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")
    fields = {
        item["key"]: item
        for item in plugin.render_config.web_payload(plugin.templates.available())
    }
    desktop_help_css = text[
        text.index(".config-help {") : text.index(".config-value-row {")
    ]

    assert 'id="config-fields" class="config-sections"' in text
    assert 'data-config-section="${esc(section.key)}"' in text
    assert 'key: "parameters"' in text
    assert 'key: "features"' in text
    assert 'key: "security"' in text
    assert 'fields.filter(field => field.type !== "boolean")' in text
    assert 'fields.filter(field => field.type === "boolean" && !field.danger)' in text
    assert 'fields.filter(field => field.type === "boolean" && field.danger)' in text
    assert ".config-section-grid {" in text
    assert ".config-section-danger {" in text
    assert 'class="panel config-panel"' in text
    assert 'class="panel runtime-panel"' in text
    assert ".runtime-panel::after" in text
    assert ".status-card::after" not in text
    assert 'data-config-section="features"' in text
    assert '.config-section[data-config-section="features"]' in text
    assert '.config-section[data-config-section="security"]' in text
    assert 'class="config-section-index"' in text
    assert 'data-tone="${esc(item.tone)}"' in text
    assert ".config-section-grid, .status-grid { grid-template-columns: 1fr; }" in text
    assert 'class="config-actions"' in text
    assert 'class="field config-field' in text
    assert "config-help-button" not in text
    assert 'class="config-help" role="tooltip"' in text
    assert 'aria-describedby="${esc(helpId)}"' in text
    assert ".config-field:hover .config-help" in desktop_help_css
    assert "focus-within" not in desktop_help_css
    assert "background: var(--panel-solid)" in desktop_help_css
    assert "position: static; display: none" in text
    assert "Chromium" in fields["render_timeout_seconds"]["hint"]
    assert fields["render_timeout_seconds"]["unit"] == "秒"
    assert fields["default_layout"]["option_labels"] == [
        "auto · 超长时分页",
        "single · 单张长图",
    ]
    assert fields["default_layout"]["options"] == ["auto", "single"]
    assert "固定纸张尺寸由 Paper 模板决定" in fields["default_layout"]["hint"]
    assert fields["max_page_height"] == {
        "key": "max_page_height",
        "label": "自动分页高度",
        "type": "number",
        "default": 3200,
        "min": 1200,
        "max": 6000,
        "step": 100,
        "unit": "CSS px",
        "hint": (
            "auto 超过该高度后按顶层语义块装箱到固定高度页面；"
            "普通聊天建议 2400–4000，默认 3200。固定 A4 模板不受影响。"
        ),
        "value": 3200,
    }


def test_preview_canvas_is_fixed_zoomable_and_pannable() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")
    preview_css = text[
        text.index(".preview-stage {") : text.index(".preview-stage.hand-active")
    ]
    wheel_js = text[
        text.index('stage.addEventListener("wheel"') : text.index(
            'stage.addEventListener("dblclick"'
        )
    ]
    panel_start = text.index(".preview-panel {")
    panel_css = text[panel_start : text.index(".preview-source {", panel_start)]

    assert "overflow: hidden" in preview_css
    assert "overscroll-behavior: contain" not in preview_css
    assert "position: static" in panel_css
    assert "position: sticky" not in panel_css
    assert 'data-preview-action="zoom-in"' in text
    assert 'data-preview-action="zoom-out"' in text
    assert 'data-preview-action="hand"' in text
    assert text.count('data-preview-action="hand" aria-pressed="false"') == 2
    assert "gallery: { zoom: 1, panX: 0, panY: 0, hand: false" in text
    assert "custom: { zoom: 1, panX: 0, panY: 0, hand: false" in text
    assert 'data-preview-action="fit"' in text
    assert "function updatePreviewTransform" in text
    assert "function initializePreviewCanvas" in text
    assert 'stage.addEventListener("pointermove"' in text
    assert "setPointerCapture" in text
    assert "event.ctrlKey || event.metaKey" in wheel_js
    assert wheel_js.index("event.ctrlKey || event.metaKey") < wheel_js.index(
        "event.preventDefault()"
    )


def test_gallery_markdown_is_docked_below_preview_with_edit_mode() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")
    viewer_markup = text[
        text.index('<section class="preview-viewer">') : text.index(
            '<section id="gallery-source"'
        )
    ]

    assert text.index('id="gallery-preview-nav"') < text.index('id="gallery-source"')
    assert 'id="gallery-source"' not in viewer_markup
    assert viewer_markup.rstrip().endswith("</section>")
    assert 'id="gallery-content-display"' in text
    assert 'id="edit-gallery-content"' in text
    assert 'aria-controls="gallery-content"' in text
    assert "function setPreviewSourceEditing" in text
    assert "function syncPreviewSource" in text
    assert "function resizePreviewSourceEditor" in text
    assert 'setPreviewSourceEditing("gallery", editing)' in text
    assert text.count("编辑示例内容后，预览会自动更新") == 2


def test_markdown_source_cards_fit_default_content_and_cap_long_text() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")
    source_css = text[
        text.index(".preview-source-code {") : text.index(".preview-toolbar {")
    ]
    resize_js = text[
        text.index("function resizePreviewSourceEditor") : text.index(
            "function syncPreviewSource"
        )
    ]

    assert "max-height: 420px" in source_css
    assert "overflow: auto" in source_css
    assert "max-height: 420px" in source_css
    assert "resize: none" in source_css
    assert "Math.min(contentHeight, maximum)" in resize_js
    assert 'contentHeight > maximum ? "auto" : "hidden"' in resize_js


def test_gallery_viewer_matches_control_row_and_stacks_on_mobile() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")
    desktop_css = text[text.index(".gallery-workspace {") : text.index(".range-row {")]
    mobile_css = text[
        text.index("@media (max-width: 820px)") : text.index(
            "@media (max-width: 560px)"
        )
    ]

    assert 'grid-template-areas: "controls preview" ". source"' in desktop_css
    assert ".gallery-workspace > .controls { grid-area: controls; }" in desktop_css
    assert "grid-template-rows: auto minmax(0,1fr) auto" in desktop_css
    assert ".gallery-workspace > .preview-source { grid-area: source;" in desktop_css
    assert "min-height: clamp(700px,calc(100vh - 160px),920px)" in text
    assert 'grid-template-areas: "controls" "preview" "source"' in mobile_css
    assert "height: 62vh; min-height: 360px" in mobile_css


def test_custom_editor_is_a_single_live_slot_with_backup_workflow() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")
    custom_form = text[
        text.index('<form id="custom-form"') : text.index(
            "</form>", text.index('<form id="custom-form"')
        )
    ]
    custom_css = text[text.index(".custom-layout {") : text.index(".custom-editor {")]

    assert 'id="custom-html"' in text
    assert 'id="custom-content"' in text
    assert 'id="custom-content"' not in custom_form
    assert 'id="custom-source" class="preview-source"' in text
    assert 'id="custom-content-display" class="preview-source-code"' in text
    assert 'id="edit-custom-content"' in text
    assert 'setPreviewSourceEditing("custom", editing)' in text
    assert text.index('id="custom-preview-nav"') < text.index('id="custom-source"')
    assert 'grid-template-areas: "editor preview" ". source"' in custom_css
    assert "grid-template-rows: auto auto minmax(560px,1fr) auto" in custom_css
    assert (
        ".custom-layout .preview-stage { height: auto; min-height: 560px; }"
        in custom_css
    )
    assert 'grid-template-areas: "editor" "preview" "source"' in text
    assert '<span class="custom-slot">custom</span>' in text
    assert 'name: "custom"' in text
    assert "scheduleCustomPreview" in text
    assert "customPreviewGeneration" in text
    assert "700" in text
    assert "立即预览" not in text
    assert "恢复默认" in text
    assert 'id="reset-custom"' in text
    assert "state.bootstrap?.default_custom_html" in text
    assert "保存 Custom" in text
    assert "编辑 Custom" in text
    assert "导出备份" in text
    assert "导入备份" in text
    assert "exportCustomBackup" in text
    assert "importCustomBackup" in text
    assert 'id="custom-name"' not in text
    assert 'id="custom-base"' not in text
    assert 'id="custom-display"' not in text
    assert 'id="custom-description"' not in text
    assert 'id="new-template"' not in text
    assert 'id="copy-template"' not in text
    assert 'id="delete-template"' not in text
    assert 'id="custom-list"' not in text
    assert "!confirm(" not in text
    assert "@media (max-width: 820px)" in text
    assert "@media (max-width: 560px)" in text


def test_studio_product_copy_avoids_internal_implementation_notes() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")

    for internal_note in [
        "只展示必要状态",
        "不泄露本机路径",
        "真实渲染管线",
        "550ms 自动刷新",
        "700ms 自动刷新",
        "连续输入不会堆满渲染队列",
    ]:
        assert internal_note not in text
    assert "查看浏览器、公式、字体、队列和最近错误" in text
    assert "一目了然" not in text
    assert "修改内容后会自动更新预览" in text
    assert "Custom 起始页" in text
    assert "自由编辑的 HTML/CSS 起始模板" in text


def test_gallery_uses_scene_and_trait_tags_instead_of_generic_capabilities() -> None:
    text = PAGE_PATH.read_text(encoding="utf-8")
    manifest = (PLUGIN_ROOT / "templates" / "manifest.json").read_text(encoding="utf-8")

    assert "function templateSceneLabel" in text
    assert 'knowledge: "知识讲解"' in text
    assert 'story: "叙事阅读"' in text
    assert 'paper: "论文排版"' in text
    assert 'custom: "自由编辑"' in text
    assert 'class="pill pill-scene"' in text
    assert '"手机阅读"' in manifest
    assert '"对白分色"' in manifest
    assert '"固定 A4"' in manifest
    assert '"Markdown"' not in manifest
    assert '"LaTeX"' not in manifest


def test_old_chat_gallery_command_is_removed() -> None:
    main_text = (PLUGIN_ROOT / "main.py").read_text(encoding="utf-8")

    assert '@filter.command("模板画廊"' not in main_text
    assert "cmd_template_gallery" not in main_text
    assert "_compose_template_gallery" not in main_text


class FakeRequest:
    def __init__(self, body=None, args=None):
        self._body = body or {}
        self.args = args or {}
        self.query = self.args

    async def json(self, default=None):
        return self._body


def test_webui_bootstrap_reports_runtime_contract(
    plugin,
    plugin_main,
    monkeypatch,
) -> None:
    plugin.config["default_layout"] = "paged"
    monkeypatch.setattr(webui_module, "json_response", lambda payload: payload)
    monkeypatch.setattr(
        diagnostics_module,
        "get_renderer_status",
        lambda: {"browser_connected": True, "last_render_seconds": 0.25},
    )
    monkeypatch.setattr(plugin.diagnostics, "has_probable_cjk_font", lambda: True)

    result = asyncio.run(plugin.webui.bootstrap())

    assert result["ok"] is True
    assert result["plugin"] == {
        "id": "astrbot_plugin_latex_render",
        "display_name": "LaTeX / Markdown 图片渲染",
        "version": plugin_main.__version__,
    }
    assert "# HTML Render Preview" in result["preview_content"]
    assert "{{content}}" in result["default_custom_html"]
    assert {"classic", "novel", "paper"} <= {
        template["name"] for template in result["templates"]
    }
    fields = {field["key"]: field for field in result["config_fields"]}
    assert fields["render_timeout_seconds"]["unit"] == "秒"
    assert fields["default_layout"]["value"] == "auto"
    assert fields["max_page_height"]["value"] == 3200
    assert fields["max_page_height"]["min"] == 1200
    assert fields["max_page_height"]["max"] == 6000
    assert fields["enable_code_highlight"]["value"] is True
    assert fields["enable_code_highlight"]["label"] == "代码高亮与语言标识"
    assert fields["trusted_html_mode"]["danger"] is True
    assert result["status"]["browser_connected"] is True
    assert result["status"]["cjk_font_available"] is True


def test_aurora_injects_classic_style_vars(plugin) -> None:
    name, _, html, _ = plugin.documents.build(
        "# 标题\n\n正文",
        "aurora",
        "user-1",
        {"classic_font_size": "30"},
        None,
    )

    assert name == "aurora"
    assert 'id="astrbot-classic-vars"' in html
    assert "--classic-font-size: 30px" in html


def test_webui_registers_all_page_routes(plugin, plugin_main) -> None:
    registered = []
    plugin.context = SimpleNamespace(
        register_web_api=lambda path, handler, methods, description: registered.append(
            (path, handler.__name__, methods, description)
        )
    )
    plugin.webui.context = plugin.context

    plugin.webui.register()

    paths = {item[0] for item in registered}
    assert {
        "/astrbot_plugin_latex_render/page/bootstrap",
        "/astrbot_plugin_latex_render/page/config",
        "/astrbot_plugin_latex_render/page/config/reset",
        "/astrbot_plugin_latex_render/page/preview",
        "/astrbot_plugin_latex_render/page/template",
        "/astrbot_plugin_latex_render/page/template/save",
        "/astrbot_plugin_latex_render/page/status",
    } <= paths
    assert all(item[2] in (["GET"], ["POST"]) for item in registered)


def test_webui_config_save_validates_and_persists(plugin, plugin_main, monkeypatch):
    saved = []
    plugin.config = {
        **plugin.config,
        "default_layout": "auto",
        "trusted_html_mode": False,
        "allow_remote_assets": False,
    }
    plugin.config["save_config"] = "sentinel"
    plugin.config = SimpleConfig(plugin.config, saved)
    plugin.render_config.raw = plugin.config
    monkeypatch.setattr(webui_module, "json_response", lambda payload: payload)
    monkeypatch.setattr(
        webui_module,
        "request",
        FakeRequest(
            {
                "values": {
                    "default_layout": "paged",
                    "render_scale": 3,
                    "max_page_height": 3600,
                    "enable_math": False,
                    "enable_code_highlight": False,
                }
            }
        ),
    )

    result = asyncio.run(plugin.webui.save_config())

    assert result["ok"] is True
    assert plugin.config["default_layout"] == "auto"
    assert plugin.config["render_scale"] == 3
    assert plugin.config["max_page_height"] == 3600
    assert plugin.config["enable_math"] is False
    assert plugin.config["enable_code_highlight"] is False
    assert saved == [True]


def test_webui_config_reset_enables_code_highlight_by_default(
    plugin, plugin_main, monkeypatch
) -> None:
    plugin.config["enable_code_highlight"] = False
    monkeypatch.setattr(webui_module, "json_response", lambda payload: payload)
    monkeypatch.setattr(webui_module, "request", FakeRequest({}))

    result = asyncio.run(plugin.webui.reset_config())

    assert result["ok"] is True
    assert result["saved"]["enable_code_highlight"] is True
    assert plugin.config["enable_code_highlight"] is True


def test_webui_custom_save_is_persistent_and_rejects_active_content(
    plugin,
    plugin_main,
    monkeypatch,
    tmp_path,
) -> None:
    custom_dir = tmp_path / "custom_templates"
    plugin.template_mgr = TemplateManager(
        str(PLUGIN_ROOT / "templates"),
        str(custom_dir),
    )
    plugin.template_mgr.ensure_custom_slot()
    plugin.templates.manager = plugin.template_mgr
    monkeypatch.setattr(webui_module, "json_response", lambda payload: payload)
    safe_html = "<style>.page{color:#234}</style><main>{{content}}</main>"
    monkeypatch.setattr(
        webui_module,
        "request",
        FakeRequest(
            {
                "name": "custom",
                "html": safe_html,
                "display_name": "Custom 起始页",
                "base_template": "classic",
            }
        ),
    )

    saved = asyncio.run(plugin.webui.save_template())

    assert saved["ok"] is True
    assert plugin.template_mgr.load_template("custom") == safe_html
    monkeypatch.setattr(
        webui_module,
        "request",
        FakeRequest(
            {
                "name": "custom",
                "html": "<script>alert(1)</script><main>{{content}}</main>",
                "base_template": "classic",
            }
        ),
    )

    rejected = asyncio.run(plugin.webui.save_template())

    assert rejected["error"] == "invalid_template"
    assert plugin.template_mgr.load_template("custom") == safe_html


class SimpleConfig(dict):
    def __init__(self, values, saved):
        super().__init__(values)
        self.saved = saved

    def save_config(self):
        self.saved.append(True)


def test_webui_draft_preview_returns_data_url(
    plugin,
    plugin_main,
    monkeypatch,
    tmp_path,
):
    image_path = tmp_path / "preview.jpg"
    image_path.write_bytes(b"\xff\xd8preview\xff\xd9")
    plugin.pipeline.render = AsyncMock(
        return_value=RenderResult(
            images=[SimpleNamespace(path=str(image_path))],
            template="classic",
            warnings=[],
            metrics={"image_count": 1, "duration_seconds": 0.1},
        )
    )
    monkeypatch.setattr(webui_module, "json_response", lambda payload: payload)
    monkeypatch.setattr(
        webui_module,
        "request",
        FakeRequest(
            {
                "template": "draft",
                "base_template": "classic",
                "template_html": "<main>{{content}}</main>",
                "content": "# 预览",
                "layout": "auto",
                "style_values": {},
            }
        ),
    )

    result = asyncio.run(plugin.webui.preview())

    assert result["ok"] is True
    assert result["images"][0].startswith("data:image/jpeg;base64,")
    plugin.pipeline.render.assert_awaited_once()
    assert plugin.pipeline.render.await_args.kwargs["template_html_override"] == (
        "<main>{{content}}</main>"
    )
