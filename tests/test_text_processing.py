from astrbot_plugin_latex_render_under_test.rendering.text import (
    contains_math,
    markdown_to_html,
)


def test_math_detection_ignores_code_and_finds_formulae() -> None:
    assert contains_math("勾股定理：$a^2+b^2=c^2$")
    assert contains_math(r"\[\int_0^1 x^2 dx\]")
    assert not contains_math("```python\nprice = '$5'\n```")
    assert not contains_math("普通文本")


def test_markdown_preserves_math_and_renders_table() -> None:
    rendered = markdown_to_html(
        "| 名称 | 公式 |\n| --- | --- |\n| 勾股定理 | $a^2+b^2=c^2$ |\n"
    )

    assert "<table>" in rendered
    assert "astr-math-inline" in rendered
    assert r"\(a^2+b^2=c^2\)" in rendered


def test_advertised_markdown_constructs_are_rendered() -> None:
    rendered = markdown_to_html(
        "# 标题\n\n- 列表项\n\n> 引用\n\n~~删除线~~\n\n```python\nprint('code')\n```"
    )

    assert "<h1>标题</h1>" in rendered
    assert "<li>列表项</li>" in rendered
    assert "<blockquote>" in rendered
    assert "<del>删除线</del>" in rendered
    assert '<code class="language-python">' in rendered


def test_fenced_code_preserves_safe_language_and_escapes_html() -> None:
    rendered = markdown_to_html("```c++\n<script>window.pwned = true</script>\n```")

    assert '<code class="language-c++">' in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;window.pwned = true&lt;/script&gt;" in rendered
