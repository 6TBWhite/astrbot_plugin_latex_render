import ast
from pathlib import Path

import docstring_parser


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PLUGIN_ROOT / "main.py"


def _main_tree() -> ast.Module:
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"))


def test_commands_use_supported_alias_keyword() -> None:
    command_decorators: list[ast.Call] = []
    for node in ast.walk(_main_tree()):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "command":
            command_decorators.append(node)

    assert command_decorators
    for decorator in command_decorators:
        keyword_names = {keyword.arg for keyword in decorator.keywords}
        assert "aliases" not in keyword_names

    aliases = {
        keyword.arg
        for decorator in command_decorators
        for keyword in decorator.keywords
    }
    assert "alias" in aliases


def test_plugin_does_not_use_deprecated_register_decorator() -> None:
    tree = _main_tree()
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    decorators = [
        decorator
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "LatexRenderPlugin"
        for decorator in node.decorator_list
    ]

    assert "register" not in imported_names
    assert decorators == []


def test_llm_tool_names_use_plugin_namespace_without_legacy_aliases() -> None:
    tool_names: set[str] = set()
    for node in ast.walk(_main_tree()):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr != "llm_tool":
                continue
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    tool_names.add(keyword.value.value)

    assert tool_names == {
        "latex_render_to_image",
        "latex_render_template_guide",
    }
    assert all(name.startswith("latex_render_") for name in tool_names)
    assert "render_to_image" not in tool_names
    assert "list_render_templates" not in tool_names


def test_llm_tool_docstring_declares_all_parameters() -> None:
    for node in ast.walk(_main_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != "latex_render_to_image_tool":
                continue
            assert [arg.arg for arg in node.args.args] == [
                "self",
                "event",
                "content",
                "template",
                "layout",
            ]
            assert [default.value for default in node.args.defaults] == ["", "", ""]
            docstring = ast.get_docstring(node) or ""
            assert "Args:" in docstring
            assert "content(string):" in docstring
            assert "template(string):" in docstring
            assert "layout(string):" in docstring
            assert "LaTeX Render 插件" not in docstring
            assert "本地 Chromium" not in docstring
            assert "不用于文生图" in docstring
            assert "图片编辑或网页截图" not in docstring
            assert "不要包裹 <render> 标签" not in docstring
            assert "留空沿用当前会话设置" in docstring
            assert "auto（自动分页）或 single（单张长图）" in docstring
            assert "旧值 paged" not in docstring
            assert "若不确定模板" not in docstring
            assert "仅在用户明确指定或已经选定模板时填写" in docstring
            assert "调用前必须" not in docstring
            assert "否则会报错" not in docstring
            parsed = docstring_parser.parse(docstring)
            assert [(param.arg_name, param.type_name) for param in parsed.params] == [
                ("content", "string"),
                ("template", "string"),
                ("layout", "string"),
            ]
            return

    raise AssertionError("latex_render_to_image_tool not found")


def test_template_query_tool_contract() -> None:
    for node in ast.walk(_main_tree()):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "latex_render_template_guide_tool":
            continue

        assert [arg.arg for arg in node.args.args] == ["self", "event", "template"]
        assert [default.value for default in node.args.defaults] == [""]
        docstring = ast.get_docstring(node) or ""
        assert "Args:" in docstring
        assert "LaTeX Render 插件" in docstring
        assert "只返回说明，不渲染或发送图片" in docstring
        assert "latex_render_to_image" in docstring
        parsed = docstring_parser.parse(docstring)
        assert [(param.arg_name, param.type_name) for param in parsed.params] == [
            ("template", "string"),
        ]

        decorators = [
            decorator
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
        ]
        assert len(decorators) == 1
        assert decorators[0].args == []
        assert [
            (keyword.arg, keyword.value.value) for keyword in decorators[0].keywords
        ] == [("name", "latex_render_template_guide")]
        return

    raise AssertionError("latex_render_template_guide_tool not found")
