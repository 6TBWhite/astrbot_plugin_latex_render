import json
from pathlib import Path

import pytest

from astrbot_plugin_latex_render_under_test.config import WEB_CONFIG_SPECS, RenderConfig
from astrbot_plugin_latex_render_under_test.preferences import PreferenceStore


class SavingConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    def save_config(self):
        self.saved += 1


def test_web_config_specs_match_astrbot_schema_defaults() -> None:
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(
            encoding="utf-8"
        )
    )
    for key, spec in WEB_CONFIG_SPECS.items():
        assert key in schema
        assert schema[key]["default"] == spec["default"]


def test_render_config_normalizes_values_and_persists() -> None:
    raw = SavingConfig(trusted_html_mode=False)
    config = RenderConfig(raw)

    values = config.normalize_web_values(
        {"render_width": 9999, "default_layout": "paged"}, ["classic"]
    )
    config.save(values)

    assert values == {"render_width": 1600, "default_layout": "auto"}
    assert raw.saved == 1


def test_render_config_rejects_remote_assets_without_trusted_mode() -> None:
    config = RenderConfig({"trusted_html_mode": False})
    with pytest.raises(ValueError, match="可信"):
        config.normalize_web_values({"allow_remote_assets": True}, ["classic"])


def test_preference_store_preserves_schema_and_normalizes_legacy_layout(
    tmp_path,
) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {"session": {"template": "novel", "layout": "paged"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = PreferenceStore(path)

    store.load()
    store.update("session", theme="dark")

    assert store.get("session") == {
        "template": "novel",
        "layout": "auto",
        "theme": "dark",
    }
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1


def test_preference_store_ignores_corruption_and_clears_template(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text("not-json", encoding="utf-8")
    store = PreferenceStore(path)
    store.load()
    assert store.entries == {}

    store.update("one", template="custom", layout="single")
    store.update("two", template="classic")
    assert store.clear_template("custom") == 1
    assert store.get("one") == {"layout": "single"}
    assert store.get("two") == {"template": "classic"}
