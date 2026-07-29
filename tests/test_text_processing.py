from text_processing import contains_math, markdown_to_html


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
