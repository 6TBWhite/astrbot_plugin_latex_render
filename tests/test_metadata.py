import re
from pathlib import Path

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_market_metadata_is_complete_and_consistent() -> None:
    metadata = yaml.safe_load(
        (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
    )
    version_source = (PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    version_match = re.search(r'__version__\s*=\s*"([^"]+)"', version_source)

    assert version_match is not None
    assert metadata["id"] == metadata["name"] == "astrbot_plugin_latex_render"
    assert metadata["version"] == version_match.group(1) == "1.2.2"
    assert metadata["type"] == "star"
    assert metadata["category"] == "工具"
    assert metadata["branch"] == "master"
    assert metadata["license"] == "MIT"
    assert metadata["short_desc"].strip()
    assert metadata["desc"].strip()
    assert "渲染与模板指南工具" in metadata["desc"]
    assert "latex_render_to_image" not in metadata["desc"]
    assert "latex_render_template_guide" not in metadata["desc"]
    assert 3 <= len(metadata["tags"]) <= 6
    assert metadata["requirements"] == []


def test_current_release_is_documented() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (PLUGIN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert (
        "img.shields.io/github/v/release/6TBWhite/astrbot_plugin_latex_render" in readme
    )
    assert "当前发布版本为 `1.2.2`" in readme
    assert "development-v1.2.2" not in readme
    assert "支持自动分页与 A4 版式" in readme
    assert "2026-08-02：v1.2.2 Agent 工具命名空间与模板指南" in changelog
    assert "v1.2.1 代码高亮与页码优化" in changelog
    assert "v1.2.0 固定页高装箱分页" in changelog
    assert "v1.1.0 渲染参数收敛与分页缓冲移除" in changelog
    assert "v1.0.8 安全分页与可视化渲染工作台" in changelog
    for marker in ("未发布", "尚未发布", "开发中"):
        assert marker not in readme
        assert marker not in changelog


def test_readme_promotes_webui_with_explicit_product_boundaries() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (PLUGIN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert readme.index("## WebUI 渲染工作台") < readme.index("## 渲染流程")
    assert "#/plugin-page/astrbot_plugin_latex_render/studio" in readme
    assert "preview API 与正式渲染共用" in readme
    assert "完整配置仍在 AstrBot 配置页" in readme
    assert "只维护一个 `custom`" in readme
    assert "公式、表格和代码块优先整体换页" in readme
    assert "WebUI 可设为 1200–6000 CSS px" in readme
    assert "首次提供独立 WebUI 渲染工作台" in changelog
    assert "消息平台发送仍由 AstrBot 消息链负责" in changelog

    for casual_copy in [
        "通天长图",
        "真正能工作的",
        "不拿通用能力充数",
        "古典调试法",
        "纯属浪费磁盘",
        "砍掉的内容",
        "标签模式让用户和 AI 都得猜",
        "工具模式让 AI 自己决策",
        '长"功能说明书"',
        '从"功能说明书"改为"决策卡片"',
        "优雅降级",
    ]:
        assert casual_copy not in readme
        assert casual_copy not in changelog


def test_requirements_only_list_imported_third_party_packages() -> None:
    requirements = (PLUGIN_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "playwright" in requirements
    assert "mistune" in requirements
    assert "Pillow" in requirements
    assert "aiohttp" not in requirements
