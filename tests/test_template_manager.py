import asyncio
from pathlib import Path

from astrbot_plugin_latex_render_under_test.template_system.manager import (
    TemplateManager,
)


def test_template_discovery_and_prompt_stripping(tmp_path) -> None:
    (tmp_path / "novel.html").write_text(
        "<!-- BUILTIN_PROMPT\n只写叙事文本。--><main>{{content}}</main>",
        encoding="utf-8",
    )
    (tmp_path / "classic.html").write_text(
        "<main>{{content}}</main>",
        encoding="utf-8",
    )
    (tmp_path / "ignored.txt").write_text("not a template", encoding="utf-8")

    manager = TemplateManager(str(tmp_path))
    asyncio.run(manager.load_templates())

    assert manager.get_available_templates() == ["classic", "novel"]
    assert "BUILTIN_PROMPT" not in manager.load_template("novel")
    assert manager.extract_builtin_prompt("novel") == "只写叙事文本。"


def test_template_id_map_is_stable(tmp_path) -> None:
    (tmp_path / "zeta.html").write_text("{{content}}", encoding="utf-8")
    (tmp_path / "alpha.html").write_text("{{content}}", encoding="utf-8")

    manager = TemplateManager(str(tmp_path))
    manager.update_template_id_map()

    assert manager.template_id_map == {1: "alpha", 2: "zeta"}


def test_invalid_template_without_content_placeholder_is_ignored(tmp_path) -> None:
    (tmp_path / "invalid.html").write_text(
        "<main>没有内容占位符</main>",
        encoding="utf-8",
    )
    manager = TemplateManager(str(tmp_path))

    assert manager.get_available_templates() == []
    try:
        manager.load_template("invalid")
    except ValueError as exc:
        assert "{{content}}" in str(exc)
    else:
        raise AssertionError("缺少内容占位符的模板不应加载成功")


def test_manifest_describes_fixed_a4_paper_template(plugin_main) -> None:
    manager = TemplateManager(str(Path(__file__).resolve().parents[1] / "templates"))
    metadata = manager.get_template_metadata("paper")

    assert metadata["display_name"].startswith("Paper")
    assert metadata["preferred_width"] == 794
    assert metadata["fixed_page"] == {
        "width": 794,
        "height": 1123,
        "top_margin": 76,
        "bottom_margin": 76,
        "content_height": 971,
    }


def test_custom_templates_are_persistent_and_do_not_override_builtins(
    tmp_path,
) -> None:
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    (builtin_dir / "classic.html").write_text(
        "<main>{{content}}</main>",
        encoding="utf-8",
    )
    (builtin_dir / "manifest.json").write_text(
        '{"templates":{"classic":{"display_name":"Classic","css_variables":[]}}}',
        encoding="utf-8",
    )
    manager = TemplateManager(str(builtin_dir), str(custom_dir))

    manager.save_custom_template(
        "my-paper",
        "<style>body{background:#fff}</style><main>{{content}}</main>",
        display_name="我的论文纸",
        base_template="classic",
    )
    reloaded = TemplateManager(str(builtin_dir), str(custom_dir))

    assert reloaded.get_available_templates() == ["classic", "my-paper"]
    assert reloaded.get_custom_templates() == ["my-paper"]
    assert reloaded.get_template_metadata("my-paper")["display_name"] == "我的论文纸"
    assert reloaded.get_template_metadata("my-paper")["editable"] is True

    try:
        reloaded.save_custom_template("classic", "<main>{{content}}</main>")
    except ValueError as exc:
        assert "内置模板为只读" in str(exc)
    else:
        raise AssertionError("自定义模板不应覆盖内置模板")


def test_single_custom_slot_is_created_once_without_overwriting_edits(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    starter_dir = builtin_dir / "_starters"
    starter_dir.mkdir()
    (builtin_dir / "classic.html").write_text(
        "<main class='classic'>{{content}}</main>",
        encoding="utf-8",
    )
    (starter_dir / "custom.default.html").write_text(
        "<main class='aurora'>{{content}}</main>",
        encoding="utf-8",
    )
    manager = TemplateManager(str(builtin_dir), str(custom_dir))

    metadata = manager.ensure_custom_slot()
    assert "class='aurora'" in manager.load_template("custom")
    assert "自由编辑的 HTML/CSS 起始模板" in metadata["description"]
    assert metadata["tags"] == ["自由改版", "HTML/CSS", "实时预览"]
    manager.save_custom_template(
        "custom",
        "<main class='edited'>{{content}}</main>",
        base_template="classic",
    )
    manager.ensure_custom_slot()

    assert metadata["display_name"] == "Custom 起始页"
    assert manager.get_custom_templates() == ["custom"]
    assert "class='edited'" in manager.load_template("custom")


def test_legacy_classic_custom_is_upgraded_without_touching_user_edits(
    tmp_path,
) -> None:
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    starter_dir = builtin_dir / "_starters"
    builtin_dir.mkdir()
    starter_dir.mkdir()
    classic = "<main class='classic'>{{content}}</main>"
    aurora = "<main class='aurora'>{{content}}</main>"
    (builtin_dir / "classic.html").write_text(classic, encoding="utf-8")
    (starter_dir / "custom.default.html").write_text(aurora, encoding="utf-8")
    manager = TemplateManager(str(builtin_dir), str(custom_dir))

    manager.save_custom_template("custom", classic, base_template="classic")
    migrated = manager.ensure_custom_slot()

    assert manager.load_template("custom") == aurora
    assert migrated["display_name"] == "Custom 起始页"
    assert migrated["tags"] == ["自由改版", "HTML/CSS", "实时预览"]

    edited = "<main class='my-own-design'>{{content}}</main>"
    manager.save_custom_template("custom", edited, base_template="classic")
    manager.ensure_custom_slot()

    assert manager.load_template("custom") == edited


def test_real_custom_starter_is_distinct_and_not_discovered_as_builtin(
    tmp_path,
) -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    manager = TemplateManager(
        str(plugin_root / "templates"),
        str(tmp_path / "custom"),
    )

    metadata = manager.ensure_custom_slot()
    html = manager.load_template("custom")

    assert manager.get_builtin_templates() == ["aurora", "classic", "novel", "paper"]
    assert manager.get_available_templates()[:4] == ["classic", "aurora", "novel", "paper"]
    assert html != manager.load_template("classic")
    assert "broadside" in html
    assert metadata["display_name"] == "Custom 起始页"
    assert "自由编辑的 HTML/CSS 起始模板" in metadata["description"]


def test_custom_template_validation_rejects_active_content(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    (builtin_dir / "classic.html").write_text(
        "<main>{{content}}</main>",
        encoding="utf-8",
    )
    manager = TemplateManager(str(builtin_dir), str(custom_dir))

    invalid_templates = [
        "<script>alert(1)</script><main>{{content}}</main>",
        '<main onclick="alert(1)">{{content}}</main>',
        '<style>@import "https://example.com/a.css";</style>{{content}}',
        '<iframe src="file:///etc/passwd"></iframe>{{content}}',
        '<img src="//localhost/private">{{content}}',
        '<meta http-equiv="refresh" content="0;url=data:text/html,x">{{content}}',
    ]
    for html in invalid_templates:
        try:
            manager.save_custom_template("unsafe", html)
        except ValueError:
            pass
        else:
            raise AssertionError("带有主动内容的自定义模板必须被拒绝")


def test_custom_template_delete_is_limited_to_custom_directory(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    (builtin_dir / "classic.html").write_text(
        "<main>{{content}}</main>",
        encoding="utf-8",
    )
    manager = TemplateManager(str(builtin_dir), str(custom_dir))
    manager.save_custom_template("temporary", "<main>{{content}}</main>")

    manager.delete_custom_template("temporary")

    assert manager.get_available_templates() == ["classic"]
    assert (builtin_dir / "classic.html").is_file()
