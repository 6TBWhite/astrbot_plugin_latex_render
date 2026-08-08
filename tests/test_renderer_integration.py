import asyncio
import hashlib
import importlib
import os
from pathlib import Path

import pytest
from PIL import Image as PILImage, ImageStat

from astrbot_plugin_latex_render_under_test.template_system.manager import (
    TemplateManager,
)
from astrbot_plugin_latex_render_under_test.rendering.models import RenderFailure
from astrbot_plugin_latex_render_under_test.rendering.renderer import (
    _fallback_render,
    _get_browser,
    close_browser,
    init_browser,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("ASTRBOT_LATEX_RENDER_INTEGRATION") != "1",
    reason="设置 ASTRBOT_LATEX_RENDER_INTEGRATION=1 后运行真实 Chromium 测试",
)


def test_real_chromium_covers_user_command_and_agent_tool(
    plugin, plugin_main, fake_event_type, collect_results
) -> None:
    command_content = (
        "# 渲染验收\n\n| 项目 | 内容 |\n| --- | --- |\n| 用户命令 | $a^2+b^2=c^2$ |"
    )
    agent_content = "## Agent 工具验收\n\n$$\\int_0^1 x^2\\,dx=\\frac{1}{3}$$"
    command_event = fake_event_type(f"/测试 {command_content}")
    agent_event = fake_event_type()
    probe_event = fake_event_type("/探针gif")

    async def exercise_entrypoints():
        try:
            await init_browser()
            command_results = await collect_results(
                plugin.cmd_test_render(command_event)
            )
            agent_results = await collect_results(
                plugin.latex_render_to_image_tool(
                    agent_event,
                    content=agent_content,
                    template="classic",
                )
            )
            probe_results = await collect_results(plugin.cmd_probe_gif(probe_event))
            return command_results, agent_results, probe_results
        finally:
            await close_browser()

    command_results, agent_results, probe_results = asyncio.run(exercise_entrypoints())

    assert len(command_results) == 1
    assert command_results[0].kind == "chain"
    assert agent_results == [
        "图片已渲染并发送给用户（font_scale=1）。可对图片内容进行简要解说。"
    ]
    assert len(agent_event.sent) == 1
    assert len(probe_results) == 2
    assert probe_results[0].kind == "plain"
    assert probe_results[1].kind == "chain"
    assert "检测到 1 个动画元素" in probe_results[1].payload[0].text
    assert len(probe_results[1].payload[1:]) == 3

    command_image = command_results[0].payload[0]
    agent_image = agent_event.sent[0].payload[0]
    probe_images = probe_results[1].payload[1:]

    expected_images = [
        (command_image, "JPEG"),
        (agent_image, "JPEG"),
        *((image, "PNG") for image in probe_images),
    ]
    for image, expected_format in expected_images:
        output_path = Path(image.path)
        assert output_path.is_file()
        assert output_path.stat().st_size > 10_000
        with PILImage.open(output_path) as rendered:
            assert rendered.format == expected_format
            assert rendered.width == 1200
            assert rendered.height >= 300
            extrema = ImageStat.Stat(rendered.convert("RGB")).extrema
            assert any(low < high for low, high in extrema)

    probe_hashes = {
        hashlib.sha256(Path(image.path).read_bytes()).hexdigest()
        for image in probe_images
    }
    assert len(probe_hashes) >= 2


def test_real_chromium_enforces_math_quality_gate(plugin, tmp_path) -> None:
    valid = (
        "行内公式 $a^2+b^2=c^2$\n\n"
        "$$\\begin{aligned}f(x)&=x^2+1\\\\g(x)&=\\frac{x}{x+1}"
        "\\end{aligned}$$\n\n"
        "$$\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$$"
    )
    too_wide = " + ".join(f"x_{{{index}}}" for index in range(80))

    async def exercise_gate():
        try:
            await init_browser()
            accepted = await plugin.pipeline.render(valid, "classic")
            failures = []
            for source in (
                r"$\frac{a}$",
                r"$\notacommand{x}$",
            ):
                try:
                    await plugin.pipeline.render(source, "classic")
                except RenderFailure as exc:
                    failures.append(exc)

            plugin.config["trusted_html_mode"] = True
            overflow_source = (
                "<style>.astr-math-block{width:240px!important}"
                ".astr-math-block svg{max-width:none!important}</style>"
                f'<div class="astr-math-block">\\[{too_wide}\\]</div>'
            )
            try:
                await plugin.pipeline.render(overflow_source, "classic")
            except RenderFailure as exc:
                failures.append(exc)
            finally:
                plugin.config["trusted_html_mode"] = False

            fallback_html = plugin.assets.inject_math(
                r'<html><head></head><body><span class="astr-math-inline">'
                r'\(\notacommand{x}\)</span></body></html>'
            )
            fallback = await _fallback_render(
                fallback_html,
                str(tmp_path / "fallback-invalid.jpg"),
                1,
                600,
                False,
                0,
                0,
            )
            bundled_mathjax = plugin.assets.mathjax_source
            plugin.assets.mathjax_source = ""
            load_failure = None
            try:
                await plugin.pipeline.render(r"$x^2$", "classic")
            except RenderFailure as exc:
                load_failure = exc
            finally:
                plugin.assets.mathjax_source = bundled_mathjax
            plain = await plugin.pipeline.render("普通文本", "classic")
            return accepted, failures, fallback, load_failure, plain
        finally:
            await close_browser()

    accepted, failures, fallback, load_failure, plain = asyncio.run(exercise_gate())

    assert accepted.metrics["math_count"] == 3
    assert [failure.code for failure in failures] == [
        "math_invalid",
        "math_invalid",
        "math_overflow",
    ]
    assert "第 1 个公式" in failures[0].message
    assert "\\notacommand" in failures[1].message
    assert not fallback.success
    assert fallback.error_code == "math_invalid"
    assert not (tmp_path / "fallback-invalid.jpg").exists()
    assert load_failure.code == "math_load_failed"
    assert plain.metrics["math_count"] == 0
    assert plain.metrics["math_gate_seconds"] < 0.1


def test_real_chromium_applies_font_scale_to_all_builtin_templates(plugin) -> None:
    plugin.config.update(
        {
            "classic_font_size": 20,
            "classic_h1_size": 30,
            "classic_h2_size": 24,
            "classic_h3_size": 20,
            "paper_font_size": 16,
            "paper_h1_size": 24,
            "paper_h2_size": 20,
            "paper_h3_size": 18,
        }
    )

    async def computed_sizes(template: str, scale: float) -> tuple[float, float]:
        _, _, html, _ = plugin.documents.build(
            "# 标题\n\n正文", template, None, None, None, scale
        )
        browser = await _get_browser()
        context = await browser.new_context(viewport={"width": 794, "height": 800})
        try:
            page = await context.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            values = await page.evaluate(
                """() => {
                    const content = document.querySelector('.content');
                    const heading = content.querySelector('h1');
                    return [
                        parseFloat(getComputedStyle(content).fontSize),
                        parseFloat(getComputedStyle(heading).fontSize),
                    ];
                }"""
            )
            return float(values[0]), float(values[1])
        finally:
            await context.close()

    async def exercise_templates():
        try:
            await init_browser()
            result = {}
            for template in ("classic", "aurora", "novel", "paper"):
                result[template] = (
                    await computed_sizes(template, 1.0),
                    await computed_sizes(template, 1.25),
                )
            return result
        finally:
            await close_browser()

    results = asyncio.run(exercise_templates())

    for normal, enlarged in results.values():
        assert enlarged[0] == pytest.approx(normal[0] * 1.25, abs=0.02)
        assert enlarged[1] == pytest.approx(normal[1] * 1.25, abs=0.02)


def test_real_chromium_paginates_to_identical_a4_pages(plugin, plugin_main) -> None:
    paragraphs = "\n\n".join(
        f"## 第 {index} 节\n\n"
        "这是一段用于验证 A4 固定纸张分页的正文。"
        "页面必须保持相同尺寸，同时尽量在 Markdown 语义块边界换页。"
        for index in range(1, 24)
    )

    async def render_paper():
        try:
            await init_browser()
            return await plugin.pipeline.render(
                f"# 固定 A4 页面测试\n\n{paragraphs}",
                "paper",
                "user-1",
                False,
            )
        finally:
            await close_browser()

    result = asyncio.run(render_paper())

    assert result.template == "paper"
    assert 2 <= len(result.images) <= 8
    for image in result.images:
        with PILImage.open(image.path) as rendered:
            assert rendered.format == "JPEG"
            assert rendered.size == (1588, 2246)
            assert rendered.getpixel((0, 0)) == (255, 255, 255)


def test_real_chromium_renders_distinct_aurora_custom_starter(
    plugin,
    plugin_main,
    tmp_path,
) -> None:
    plugin.template_mgr = TemplateManager(
        str(Path(__file__).resolve().parents[1] / "templates"),
        str(tmp_path / "custom_templates"),
    )
    metadata = plugin.template_mgr.ensure_custom_slot()
    plugin.template_mgr.update_template_id_map()
    plugin.templates.manager = plugin.template_mgr

    async def render_custom():
        try:
            await init_browser()
            return await plugin.pipeline.render(
                "# Aurora 灵感\n\n"
                "> 这是一张独立的深色 Custom 模板。\n\n"
                "- 摘要\n- 公式 $a^2+b^2=c^2$\n\n"
                "```python\nprint('custom')\n```",
                "custom",
                "user-1",
                False,
            )
        finally:
            await close_browser()

    result = asyncio.run(render_custom())

    assert metadata["display_name"] == "Custom 起始页"
    assert result.template == "custom"
    assert len(result.images) == 1
    with PILImage.open(result.images[0].path) as rendered:
        assert rendered.format == "JPEG"
        assert rendered.width == 1200
        assert rendered.height >= 500
        mean = ImageStat.Stat(rendered.convert("RGB")).mean
        assert sum(mean) / len(mean) > 150


def test_real_chromium_highlights_explicit_languages_across_templates(
    plugin,
    plugin_main,
    tmp_path,
) -> None:
    plugin.template_mgr = TemplateManager(
        str(Path(__file__).resolve().parents[1] / "templates"),
        str(tmp_path / "custom_templates"),
    )
    plugin.template_mgr.ensure_custom_slot()
    plugin.template_mgr.update_template_id_map()
    plugin.templates.manager = plugin.template_mgr
    renderer = importlib.import_module(f"{plugin_main.__package__}.rendering.renderer")
    source = """
```python
def greet(name):
    return f"hello {name}"
```

```js
const answer = "forty-two";
```

```json
{"answer": 42}
```

```sh
if test -n "$HOME"; then echo ready; fi
```

```c++
int main() { return 0; }
```

```mysterylang
plain unknown language
```

```
plain unlabelled code
```
"""

    async def inspect_templates():
        states = {}
        novel_result = None
        disabled_state = None
        disabled_result = None
        try:
            await init_browser()
            browser = await renderer._get_browser()
            assert browser is not None
            for template in ("classic", "novel", "paper", "custom"):
                _, _, html, _ = plugin.documents.build(
                    source, template, "user-1", None, None
                )
                context = await browser.new_context(
                    viewport={"width": 794, "height": 800}
                )
                page = await context.new_page()
                try:
                    await renderer._install_network_policy(page)
                    await page.set_content(html, wait_until="domcontentloaded")
                    await renderer._prepare_page_for_capture(page, 794)
                    states[template] = await page.evaluate(
                        """() => ({
                            ready: window.__ASTR_CODE_HIGHLIGHT_READY__,
                            theme: document.querySelector(
                                '#astrbot-code-highlight-theme'
                            )?.dataset.theme,
                            blocks: Array.from(document.querySelectorAll('pre > code')).map(
                                block => ({
                                    language: Array.from(block.classList).find(
                                        name => name.startsWith('language-')
                                    ) || '',
                                    highlighted: block.classList.contains('hljs'),
                                    tokens: block.querySelectorAll('[class^="hljs-"]').length,
                                    label: block.parentElement.querySelector(
                                        ':scope > .astr-code-language'
                                    )?.textContent || ''
                                })
                            )
                        })"""
                    )
                finally:
                    await context.close()

            novel_result = await plugin.pipeline.render(
                source, "novel", "user-1", False
            )

            plugin.config["enable_code_highlight"] = False
            _, _, disabled_html, _ = plugin.documents.build(
                source, "classic", "user-1", None, None
            )
            context = await browser.new_context(viewport={"width": 794, "height": 800})
            page = await context.new_page()
            try:
                await renderer._install_network_policy(page)
                await page.set_content(disabled_html, wait_until="domcontentloaded")
                await renderer._prepare_page_for_capture(page, 794)
                disabled_state = await page.evaluate(
                    """() => ({
                        readyDefined: Object.prototype.hasOwnProperty.call(
                            window, '__ASTR_CODE_HIGHLIGHT_READY__'
                        ),
                        theme: document.querySelector(
                            '#astrbot-code-highlight-theme'
                        )?.dataset.theme || '',
                        blocks: Array.from(document.querySelectorAll('pre > code')).map(
                            block => ({
                                text: block.textContent,
                                language: Array.from(block.classList).find(
                                    name => name.startsWith('language-')
                                ) || '',
                                highlighted: block.classList.contains('hljs'),
                                tokens: block.querySelectorAll('[class^="hljs-"]').length,
                                label: block.parentElement.querySelector(
                                    ':scope > .astr-code-language'
                                )?.textContent || ''
                            })
                        )
                    })"""
                )
            finally:
                await context.close()

            disabled_result = await plugin.pipeline.render(
                source, "classic", "user-1", False
            )
            return states, novel_result, disabled_state, disabled_result
        finally:
            await close_browser()

    states, novel_result, disabled_state, disabled_result = asyncio.run(
        inspect_templates()
    )

    expected_themes = {
        "classic": "github-dark",
        "novel": "docco",
        "paper": "github",
        "custom": "night-owl",
    }
    for template, state in states.items():
        assert state["ready"] is True
        assert state["theme"] == expected_themes[template]
        assert [block["label"] for block in state["blocks"]] == [
            "Python",
            "JavaScript",
            "JSON",
            "Bash",
            "C++",
            "MYSTERYLANG",
            "",
        ]
        assert all(block["highlighted"] for block in state["blocks"][:5])
        assert all(block["tokens"] > 0 for block in state["blocks"][:5])
        assert state["blocks"][5]["highlighted"] is False
        assert state["blocks"][5]["tokens"] == 0
        assert state["blocks"][6]["highlighted"] is False
        assert state["blocks"][6]["tokens"] == 0

    assert novel_result.template == "novel"
    assert novel_result.images
    with PILImage.open(novel_result.images[0].path) as rendered:
        assert rendered.format == "JPEG"
        assert rendered.width == 1200

    assert disabled_state["readyDefined"] is False
    assert disabled_state["theme"] == ""
    assert [block["language"] for block in disabled_state["blocks"]] == [
        "language-python",
        "language-js",
        "language-json",
        "language-sh",
        "language-c++",
        "language-mysterylang",
        "",
    ]
    assert all(not block["highlighted"] for block in disabled_state["blocks"])
    assert all(block["tokens"] == 0 for block in disabled_state["blocks"])
    assert all(block["label"] == "" for block in disabled_state["blocks"])
    assert "plain unknown language" in disabled_state["blocks"][5]["text"]
    assert disabled_result.template == "classic"
    assert disabled_result.images
    with PILImage.open(disabled_result.images[0].path) as rendered:
        assert rendered.format == "JPEG"
        assert rendered.width == 1200
