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


def test_llm_tool_docstring_declares_all_parameters() -> None:
    for node in ast.walk(_main_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != "render_to_image_tool":
                continue
            docstring = ast.get_docstring(node) or ""
            assert "Args:" in docstring
            assert "content(string):" in docstring
            assert "template(string):" in docstring
            parsed = docstring_parser.parse(docstring)
            assert [(param.arg_name, param.type_name) for param in parsed.params] == [
                ("content", "string"),
                ("template", "string"),
            ]
            return

    raise AssertionError("render_to_image_tool not found")
