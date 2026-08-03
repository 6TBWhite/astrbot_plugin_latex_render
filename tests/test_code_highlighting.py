from __future__ import annotations

import json
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _document(code_class: str = "language-python") -> str:
    return (
        "<!doctype html><html><head></head><body>"
        f'<pre><code class="{code_class}">print(&quot;hello&quot;)</code></pre>'
        "</body></html>"
    )


@pytest.mark.parametrize(
    ("scene", "theme"),
    [
        ("knowledge", "github-dark"),
        ("story", "docco"),
        ("paper", "github"),
        ("custom", "night-owl"),
        ("unknown", "github"),
    ],
)
def test_code_highlight_injection_selects_scene_theme(
    plugin, scene: str, theme: str
) -> None:
    rendered = plugin.assets.inject_code_highlight(_document(), scene)

    assert f'data-theme="{theme}"' in rendered
    assert "data-astrbot-code-highlight-loader" in rendered
    assert "window.__ASTR_CODE_HIGHLIGHT_READY__ = false" in rendered
    assert "highlightAuto" not in rendered
    assert "<script src=" not in rendered
    assert "<link href=" not in rendered


def test_code_highlight_injection_is_idempotent(plugin) -> None:
    rendered = plugin.assets.inject_code_highlight(_document(), "knowledge")

    assert plugin.assets.inject_code_highlight(rendered, "knowledge") == rendered
    assert rendered.count("data-astrbot-code-highlight-loader") == 1


def test_code_highlight_defaults_to_enabled_for_legacy_config(plugin) -> None:
    plugin.config.pop("enable_code_highlight")

    rendered = plugin.assets.inject_code_highlight(_document(), "knowledge")

    assert "data-astrbot-code-highlight-loader" in rendered


def test_code_highlight_switch_disables_assets_and_language_label(
    plugin, monkeypatch
) -> None:
    plugin.config["enable_code_highlight"] = False
    monkeypatch.setattr(
        plugin.assets,
        "load_code_highlight",
        lambda _theme: pytest.fail("关闭高亮时不应读取高亮资源"),
    )
    source = _document()

    rendered = plugin.assets.inject_code_highlight(source, "knowledge")

    assert rendered == source
    assert 'class="language-python"' in rendered
    assert "print(&quot;hello&quot;)" in rendered
    assert "data-astrbot-code-highlight-loader" not in rendered
    assert "astr-code-language" not in rendered
    assert "__ASTR_CODE_HIGHLIGHT_READY__" not in rendered


def test_code_highlight_config_schema_defaults_to_enabled() -> None:
    schema = json.loads((PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

    field = schema["enable_code_highlight"]
    assert field["type"] == "bool"
    assert field["default"] is True
    assert field["description"] == "代码高亮与语言标识"


def test_unlabelled_code_does_not_load_highlighter(plugin) -> None:
    source = _document("")

    assert plugin.assets.inject_code_highlight(source, "knowledge") == source


def test_trusted_raw_html_does_not_load_highlighter(plugin) -> None:
    plugin.config["trusted_html_mode"] = True
    source = (
        "<style>body { color: white; }</style>"
        '<pre><code class="language-python">print(1)</code></pre>'
    )

    _, _, rendered, trusted_mode = plugin.documents.build(
        source, "classic", "user-1", None, None
    )

    assert trusted_mode is True
    assert "data-astrbot-code-highlight-loader" not in rendered


def test_missing_highlight_assets_fall_back_to_plain_code(plugin, monkeypatch) -> None:
    monkeypatch.setattr(plugin.assets, "load_code_highlight", lambda _theme: None)
    source = _document()

    assert plugin.assets.inject_code_highlight(source, "knowledge") == source


def test_disabled_highlight_keeps_markdown_fenced_code(plugin) -> None:
    plugin.config["enable_code_highlight"] = False

    _, _, rendered, trusted_mode = plugin.documents.build(
        '```python\nprint("hello")\n```',
        "classic",
        "user-1",
        None,
        None,
    )

    assert trusted_mode is False
    assert '<code class="language-python">' in rendered
    assert "print(&quot;hello&quot;)" in rendered
    assert "data-astrbot-code-highlight-loader" not in rendered
    assert "astr-code-language" not in rendered
