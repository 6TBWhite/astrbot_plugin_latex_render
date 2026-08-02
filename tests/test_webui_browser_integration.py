import asyncio
import base64
import json
import os
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PAGE_PATH = PLUGIN_ROOT / "pages" / "studio" / "index.html"

pytestmark = pytest.mark.skipif(
    os.environ.get("ASTRBOT_LATEX_RENDER_INTEGRATION") != "1",
    reason="设置 ASTRBOT_LATEX_RENDER_INTEGRATION=1 后运行真实 WebUI 浏览器测试",
)


def _preview_image_data_url() -> str:
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" width="600" height="800">
      <rect width="600" height="800" fill="white"/>
      <rect x="40" y="40" width="520" height="720" rx="12"
        fill="#f7f5ee" stroke="#244d38" stroke-width="8"/>
      <text x="70" y="100" font-size="28" fill="#173326">Render Preview</text>
    </svg>
    """
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _bridge_script() -> str:
    preview_content = """# HTML Render Preview

这是一段模板预览文本。
这里会测试普通段落、列表、代码块和数学公式。

- 项目一
- 项目二

```python
print("Hello from AstrBot")
```

行内公式 $a^2 + b^2 = c^2$

$$
\\int_0^1 x^2 dx = \\frac{1}{3}
$$
"""
    config_fields = [
        {
            "key": "default_template",
            "label": "默认模板",
            "type": "select",
            "default": "",
            "value": "classic",
            "options": ["", "classic", "paper", "custom"],
            "option_labels": ["自动选择", "classic", "paper", "custom"],
            "hint": "未显式指定模板时使用。",
        },
        {
            "key": "default_layout",
            "label": "默认布局",
            "type": "select",
            "default": "auto",
            "value": "auto",
            "options": ["auto", "single"],
            "option_labels": [
                "auto · 超长时分页",
                "single · 单张长图",
            ],
            "hint": "固定纸张尺寸由 Paper 模板决定。",
        },
        {
            "key": "max_page_height",
            "label": "自动分页高度",
            "type": "number",
            "default": 3200,
            "value": 3200,
            "min": 1200,
            "max": 6000,
            "step": 100,
            "unit": "CSS px",
            "hint": "普通聊天建议 2400–4000，默认 3200。",
        },
        {
            "key": "render_width",
            "label": "渲染宽度",
            "type": "number",
            "default": 600,
            "value": 600,
            "min": 320,
            "max": 1600,
            "step": 1,
            "hint": "控制普通模板的 CSS 排版宽度。",
        },
        {
            "key": "render_timeout_seconds",
            "label": "渲染超时",
            "type": "number",
            "default": 30,
            "value": 30,
            "min": 5,
            "max": 180,
            "step": 1,
            "unit": "秒",
            "hint": "限制任务从排队到 Chromium 排版完成的最长等待时间。",
        },
        {
            "key": "enable_markdown",
            "label": "Markdown 渲染",
            "type": "boolean",
            "default": True,
            "value": True,
            "hint": "启用 Markdown 排版。",
        },
        {
            "key": "enable_code_highlight",
            "label": "代码高亮与语言标识",
            "type": "boolean",
            "default": True,
            "value": True,
            "hint": "高亮显式标注语言的代码块并显示语言名称。",
        },
        {
            "key": "show_page_numbers",
            "label": "多页显示页码",
            "type": "boolean",
            "default": True,
            "value": True,
            "hint": "在分页结果中显示页码。",
        },
        {
            "key": "trusted_html_mode",
            "label": "可信 HTML/CSS 模式",
            "type": "boolean",
            "default": False,
            "value": False,
            "danger": True,
            "hint": "仅适合可信内容和私人部署。",
        },
        {
            "key": "allow_remote_assets",
            "label": "允许远程资源",
            "type": "boolean",
            "default": False,
            "value": False,
            "danger": True,
            "hint": "可能产生隐私和内网访问风险。",
        },
    ]
    style_controls = [
        {
            "key": key,
            "label": label,
            "default": value,
            "value": value,
            "min": minimum,
            "max": maximum,
            "step": step,
            "unit": unit,
        }
        for key, label, value, minimum, maximum, step, unit in [
            ("classic_body_padding", "外圈边距", 18, 0, 48, 1, "px"),
            ("classic_page_padding_y", "画布上下留白", 32, 8, 96, 1, "px"),
            ("classic_page_padding_x", "画布左右留白", 28, 8, 96, 1, "px"),
            ("classic_font_size", "正文字号", 22, 12, 34, 1, "px"),
            ("classic_line_height", "正文行高", 1.8, 1.2, 2.4, 0.05, ""),
            ("classic_h1_size", "一级标题", 31, 20, 48, 1, "px"),
            ("classic_h2_size", "二级标题", 26, 18, 42, 1, "px"),
            ("classic_h3_size", "三级标题", 23, 16, 36, 1, "px"),
        ]
    ]
    templates = [
        {
            "name": "classic",
            "display_name": "Classic 知识卡",
            "description": "手机阅读的讲题卡：长文按页分屏，公式、代码与表格一页一屏。",
            "scene": "knowledge",
            "tags": ["手机阅读", "讲题讲解", "公式推导", "代码示例"],
            "source": "builtin",
            "editable": False,
            "base_template": "classic",
            "controls": style_controls,
            "fixed_page": None,
        },
        {
            "name": "paper",
            "display_name": "Paper A4 论文页",
            "description": "纯白 A4 固定纸张。",
            "scene": "paper",
            "tags": ["固定 A4", "等尺寸分页", "打印友好"],
            "source": "builtin",
            "editable": False,
            "base_template": "paper",
            "controls": [],
            "fixed_page": {"width": 794, "height": 1123},
        },
        {
            "name": "custom",
            "display_name": "Aurora 灵感卡",
            "description": "深色渐变卡片，适合灵感记录、摘要与展示；可在 Custom 编辑中自由改版。",
            "scene": "custom",
            "tags": ["自由改版", "HTML/CSS", "实时预览"],
            "source": "custom",
            "editable": True,
            "base_template": "classic",
            "controls": [],
            "fixed_page": None,
        },
    ]
    bootstrap = {
        "ok": True,
        "plugin": {
            "id": "astrbot_plugin_latex_render",
            "display_name": "LaTeX / Markdown 图片渲染",
            "version": "1.0.9",
        },
        "config_fields": config_fields,
        "templates": templates,
        "preview_content": preview_content,
        "status": {
            "browser_connected": True,
            "browser_launching": False,
            "mathjax_available": True,
            "cjk_font_available": True,
            "active_renders": 0,
            "queued_renders": 0,
            "template_count": 3,
            "custom_template_count": 1,
            "last_render_seconds": 0.12,
            "last_metrics": {},
            "last_error": {},
            "cooldown_seconds": 0,
        },
    }
    payload = json.dumps(
        {
            "bootstrap": bootstrap,
            "previewImage": _preview_image_data_url(),
            "customHtml": (
                "<!doctype html><html><body style='background:#090b18'>"
                "<main class='aurora-card'>{{content}}</main></body></html>"
            ),
        },
        ensure_ascii=False,
    )
    return f"""
      (() => {{
        const mock = {payload};
        const clone = value => JSON.parse(JSON.stringify(value));
        window.__bridgeCalls = [];
        window.AstrBotPluginPage = {{
          ready: async () => true,
          apiGet: async (route, params = {{}}) => {{
            window.__bridgeCalls.push({{method: "GET", route, params}});
            if (route === "page/bootstrap") return clone(mock.bootstrap);
            if (route === "page/status") {{
              return {{ok: true, status: clone(mock.bootstrap.status)}};
            }}
            if (route === "page/template") {{
              return {{
                ok: true,
                name: "custom",
                html: mock.customHtml,
                metadata: {{base_template: "classic", editable: true}},
              }};
            }}
            return {{error: "missing_mock", message: route}};
          }},
          apiPost: async (route, body = {{}}) => {{
            window.__bridgeCalls.push({{method: "POST", route, body}});
            if (route === "page/preview") {{
              return {{
                ok: true,
                images: [mock.previewImage],
                warnings: [],
                metrics: {{image_count: 1}},
              }};
            }}
            if (route === "page/config" || route === "page/config/reset") {{
              return {{
                ok: true,
                config_fields: clone(mock.bootstrap.config_fields),
                templates: clone(mock.bootstrap.templates),
              }};
            }}
            if (route === "page/template/save") {{
              return {{
                ok: true,
                metadata: {{name: "custom", base_template: "classic"}},
                templates: clone(mock.bootstrap.templates),
              }};
            }}
            return {{error: "missing_mock", message: route}};
          }},
        }};
      }})();
    """


async def _exercise_webui() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1360, "height": 720})
        try:
            await page.add_init_script(_bridge_script())
            await page.goto(PAGE_PATH.as_uri())
            await page.locator('[data-config-section="parameters"]').wait_for()

            section_titles = await page.locator(
                ".config-section-head h3"
            ).all_text_contents()
            assert section_titles == ["基础参数", "功能开关", "安全与网络"]
            assert await page.get_by_text("代码高亮与语言标识", exact=True).is_visible()
            assert await page.locator(".config-help-button").count() == 0
            page_height_input = page.locator('[data-config-key="max_page_height"]')
            assert await page_height_input.is_visible()
            assert await page_height_input.input_value() == "3200"
            assert await page_height_input.get_attribute("min") == "1200"
            assert await page_height_input.get_attribute("max") == "6000"
            assert (
                await page_height_input.locator("xpath=..")
                .get_by_text("CSS px", exact=True)
                .is_visible()
            )
            layout_options = await page.locator(
                "#config-default_layout option"
            ).evaluate_all("nodes => nodes.map(node => node.textContent.trim())")
            assert layout_options == [
                "auto · 超长时分页",
                "single · 单张长图",
            ]
            section_styles = await page.locator(".config-section").evaluate_all(
                """nodes => nodes.map(node => ({
                  border: getComputedStyle(node).borderColor,
                  background: getComputedStyle(node).backgroundImage,
                }))"""
            )
            assert len({item["border"] for item in section_styles}) == 3
            assert all(item["background"] != "none" for item in section_styles)
            assert await page.locator(".config-section-index").all_text_contents() == [
                "01",
                "02",
                "03",
            ]
            status_tones = await page.locator(".status-card").evaluate_all(
                "nodes => nodes.map(node => node.dataset.tone)"
            )
            assert {"success", "info", "accent"} <= set(status_tones)
            assert (
                await page.locator(".runtime-panel").evaluate(
                    'node => getComputedStyle(node, "::after").content'
                )
                != "none"
            )
            assert (
                await page.locator(".status-card").first.evaluate(
                    'node => getComputedStyle(node, "::after").content'
                )
                == "none"
            )

            timeout_card = page.locator(".config-field").filter(has_text="渲染超时")
            await timeout_card.hover()
            await page.wait_for_timeout(200)
            timeout_help = timeout_card.locator(".config-help")
            assert await timeout_help.is_visible()
            assert (
                await timeout_help.evaluate(
                    "node => getComputedStyle(node).backgroundColor"
                )
                == "rgb(255, 255, 255)"
            )

            await page.get_by_role("tab", name="模板画廊").click()
            await page.locator("#gallery-preview img").wait_for()
            assert await page.locator("#gallery-layout option").evaluate_all(
                "nodes => nodes.map(node => node.value)"
            ) == ["auto", "single"]
            assert (
                await page.locator(".template-card")
                .filter(has_text="Classic 知识卡")
                .get_by_text("讲题讲解", exact=True)
                .is_visible()
            )
            assert (
                await page.locator(".template-card")
                .filter(has_text="Aurora 灵感卡")
                .get_by_text("自由改版", exact=True)
                .is_visible()
            )
            stage = page.locator("#gallery-preview")
            gallery_hand = page.locator(
                '[data-preview-kind="gallery"][data-preview-action="hand"]'
            )
            assert await gallery_hand.get_attribute("aria-pressed") == "false"
            assert "hand-active" not in (await stage.get_attribute("class") or "")
            await gallery_hand.click()
            assert await gallery_hand.get_attribute("aria-pressed") == "true"
            await gallery_hand.click()
            assert await gallery_hand.get_attribute("aria-pressed") == "false"
            await stage.scroll_into_view_if_needed()
            await stage.hover()
            scroll_before = await page.evaluate("window.scrollY")
            await page.mouse.wheel(0, 420)
            await page.wait_for_timeout(100)
            scroll_after = await page.evaluate("window.scrollY")
            assert scroll_after > scroll_before

            await stage.hover()
            zoom_before = await page.locator("#gallery-preview-zoom").text_content()
            scroll_before_zoom = await page.evaluate("window.scrollY")
            await page.keyboard.down("Control")
            await page.mouse.wheel(0, -240)
            await page.keyboard.up("Control")
            await page.wait_for_timeout(100)
            assert (
                await page.locator("#gallery-preview-zoom").text_content()
                != zoom_before
            )
            assert await page.evaluate("window.scrollY") == scroll_before_zoom

            gallery_source_metrics = await page.locator(
                "#gallery-content-display"
            ).evaluate(
                """node => ({
                  clientHeight: node.clientHeight,
                  scrollHeight: node.scrollHeight,
                })"""
            )
            assert gallery_source_metrics["scrollHeight"] <= (
                gallery_source_metrics["clientHeight"] + 1
            )

            await page.get_by_role("tab", name="Custom 编辑").click()
            await page.locator("#custom-preview img").wait_for()
            custom_hand = page.locator(
                '[data-preview-kind="custom"][data-preview-action="hand"]'
            )
            assert await custom_hand.get_attribute("aria-pressed") == "false"
            editor_box = await page.locator(".custom-editor-panel").bounding_box()
            preview_box = await page.locator(".custom-preview-panel").bounding_box()
            stage_box = await page.locator("#custom-preview").bounding_box()
            source_box = await page.locator("#custom-source").bounding_box()
            assert editor_box and preview_box and stage_box and source_box
            assert abs(editor_box["height"] - preview_box["height"]) <= 2
            assert stage_box["height"] >= 558
            assert source_box["y"] >= preview_box["y"] + preview_box["height"]

            await page.locator("#edit-custom-content").click()
            custom_editor = page.locator("#custom-content")
            await custom_editor.fill(
                "\n".join(f"第 {index} 行" for index in range(180))
            )
            await page.wait_for_timeout(50)
            long_source_metrics = await custom_editor.evaluate(
                """node => ({
                  clientHeight: node.clientHeight,
                  scrollHeight: node.scrollHeight,
                  overflowY: getComputedStyle(node).overflowY,
                })"""
            )
            assert long_source_metrics["clientHeight"] <= 420
            assert (
                long_source_metrics["scrollHeight"]
                > long_source_metrics["clientHeight"]
            )
            assert long_source_metrics["overflowY"] == "auto"

            await page.set_viewport_size({"width": 760, "height": 760})
            editor_box = await page.locator(".custom-editor-panel").bounding_box()
            preview_box = await page.locator(".custom-preview-panel").bounding_box()
            source_box = await page.locator("#custom-source").bounding_box()
            assert editor_box and preview_box and source_box
            assert editor_box["y"] < preview_box["y"] < source_box["y"]
        finally:
            await browser.close()


def test_real_browser_webui_main_interactions() -> None:
    asyncio.run(_exercise_webui())
