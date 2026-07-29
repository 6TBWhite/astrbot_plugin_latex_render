import asyncio

from core.template_manager import TemplateManager


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
