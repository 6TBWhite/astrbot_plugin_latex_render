from __future__ import annotations

import pytest


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
    rendered = plugin._inject_code_highlight_assets(_document(), scene)

    assert f'data-theme="{theme}"' in rendered
    assert "data-astrbot-code-highlight-loader" in rendered
    assert "window.__ASTR_CODE_HIGHLIGHT_READY__ = false" in rendered
    assert "highlightAuto" not in rendered
    assert "<script src=" not in rendered
    assert "<link href=" not in rendered


def test_code_highlight_injection_is_idempotent(plugin) -> None:
    rendered = plugin._inject_code_highlight_assets(_document(), "knowledge")

    assert plugin._inject_code_highlight_assets(rendered, "knowledge") == rendered
    assert rendered.count("data-astrbot-code-highlight-loader") == 1


def test_unlabelled_code_does_not_load_highlighter(plugin) -> None:
    source = _document("")

    assert plugin._inject_code_highlight_assets(source, "knowledge") == source


def test_trusted_raw_html_does_not_load_highlighter(plugin) -> None:
    plugin.config["trusted_html_mode"] = True
    source = (
        "<style>body { color: white; }</style>"
        '<pre><code class="language-python">print(1)</code></pre>'
    )

    _, _, rendered, trusted_mode = plugin._prepare_render_document(
        source, "classic", "user-1", None, None
    )

    assert trusted_mode is True
    assert "data-astrbot-code-highlight-loader" not in rendered


def test_missing_highlight_assets_fall_back_to_plain_code(plugin, monkeypatch) -> None:
    monkeypatch.setattr(plugin, "_load_code_highlight_assets", lambda _theme: None)
    source = _document()

    assert plugin._inject_code_highlight_assets(source, "knowledge") == source
