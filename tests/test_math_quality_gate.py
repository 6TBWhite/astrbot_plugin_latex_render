import pytest

from astrbot_plugin_latex_render_under_test.rendering.math_quality import (
    MathQualityError,
    validate_math_snapshot,
)


def test_math_quality_gate_accepts_complete_visible_svg() -> None:
    metrics = validate_math_snapshot(
        {
            "state": "ready",
            "items": [
                {
                    "index": 1,
                    "rendered": True,
                    "svg": True,
                    "error": "",
                    "width": 120,
                    "height": 32,
                    "overflow": False,
                }
            ],
        },
        0.125,
    )

    assert metrics == {"math_count": 1, "math_gate_seconds": 0.125}


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        ({"state": "failed", "items": []}, "math_load_failed"),
        ({"state": "timeout", "items": []}, "math_timeout"),
        (
            {
                "state": "ready",
                "items": [
                    {
                        "index": 1,
                        "rendered": True,
                        "svg": True,
                        "error": "Missing argument for \\frac",
                        "width": 100,
                        "height": 20,
                        "overflow": False,
                    }
                ],
            },
            "math_invalid",
        ),
        (
            {
                "state": "ready",
                "items": [
                    {
                        "index": 1,
                        "rendered": False,
                        "svg": False,
                        "error": "",
                        "width": 0,
                        "height": 0,
                        "overflow": False,
                    }
                ],
            },
            "math_incomplete",
        ),
        (
            {
                "state": "ready",
                "items": [
                    {
                        "index": 1,
                        "rendered": True,
                        "svg": True,
                        "error": "",
                        "width": 0,
                        "height": 20,
                        "overflow": False,
                    }
                ],
            },
            "math_incomplete",
        ),
        (
            {
                "state": "ready",
                "items": [
                    {
                        "index": 1,
                        "rendered": True,
                        "svg": True,
                        "error": "",
                        "width": 100,
                        "height": 20,
                        "overflow": True,
                    }
                ],
            },
            "math_overflow",
        ),
    ],
)
def test_math_quality_gate_rejects_each_failure_class(snapshot, code) -> None:
    with pytest.raises(MathQualityError) as caught:
        validate_math_snapshot(snapshot, 0.01)

    assert caught.value.code == code


def test_math_quality_error_is_bounded_and_redacts_local_paths() -> None:
    detail = "Missing argument " + r"C:\private\formula.tex " + "x" * 500
    snapshot = {
        "state": "ready",
        "items": [
            {
                "index": 2,
                "rendered": True,
                "svg": True,
                "error": detail,
                "width": 100,
                "height": 20,
                "overflow": False,
            }
        ],
    }

    with pytest.raises(MathQualityError) as caught:
        validate_math_snapshot(snapshot, 0.01)

    assert caught.value.code == "math_invalid"
    assert "第 2 个公式" in caught.value.message
    assert "private" not in caught.value.message
    assert len(caught.value.message) < 230
