import asyncio

import pytest

from astrbot_plugin_latex_render_under_test.config import normalize_font_scale
from astrbot_plugin_latex_render_under_test.rendering.models import RenderFailure


def test_normalize_font_scale_rejects_invalid_and_clamps_bounds() -> None:
    assert normalize_font_scale(0.1) == 0.75
    assert normalize_font_scale(1.23456) == 1.235
    assert normalize_font_scale(9) == 1.5
    with pytest.raises(ValueError, match="必须是有限数字"):
        normalize_font_scale(float("nan"))


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (
            "classic",
            {
                "--classic-font-size": "25px",
                "--classic-h1-size": "37.5px",
                "--classic-h2-size": "30px",
                "--classic-h3-size": "25px",
            },
        ),
        (
            "aurora",
            {
                "--classic-font-size": "25px",
                "--classic-h1-size": "37.5px",
                "--classic-h2-size": "30px",
                "--classic-h3-size": "25px",
            },
        ),
        (
            "paper",
            {
                "--paper-font-size": "20px",
                "--paper-h1-size": "30px",
                "--paper-h2-size": "25px",
                "--paper-h3-size": "22.5px",
            },
        ),
        (
            "novel",
            {
                "--novel-font-size": "22.5px",
                "--novel-h1-size": "30px",
                "--novel-h2-size": "22.5px",
                "--novel-h3-size": "22.5px",
            },
        ),
    ],
)
def test_builtin_templates_apply_one_render_font_scale(
    plugin, template: str, expected: dict[str, str]
) -> None:
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

    html = plugin.templates.apply("正文", template, font_scale=1.25)

    for variable, value in expected.items():
        assert f"{variable}: {value}" in html
    assert "--astr-table-font-size: 17.5px" in html


def test_font_scale_does_not_persist_between_renders(plugin) -> None:
    plugin.config["classic_font_size"] = 20

    enlarged = plugin.templates.apply("正文", "classic", font_scale=1.25)
    normal = plugin.templates.apply("正文", "classic")

    assert "--classic-font-size: 25px" in enlarged
    assert "--classic-font-size: 20px" in normal


def test_custom_template_rejects_non_default_font_scale(plugin) -> None:
    with pytest.raises(RenderFailure) as caught:
        asyncio.run(
            plugin.pipeline.render("正文", "custom", font_scale=1.1)
        )

    assert caught.value.code == "unsupported_font_scale"
    assert "Custom 模板" in caught.value.message
