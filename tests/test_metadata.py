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
    assert metadata["version"] == version_match.group(1) == "1.0.8"
    assert metadata["type"] == "star"
    assert metadata["category"] == "工具"
    assert metadata["branch"] == "master"
    assert metadata["license"] == "MIT"
    assert metadata["short_desc"].strip()
    assert metadata["desc"].strip()
    assert 3 <= len(metadata["tags"]) <= 6
    assert metadata["requirements"] == []


def test_v107_is_documented_as_unreleased_development_version() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (PLUGIN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "release-v1.0.8" in readme
    assert "当前发布版本为 `1.0.8`" in readme
    assert "development-v1.0.8" not in readme
    assert "v1.0.8 安全分页与可视化渲染工作台" in changelog
    assert "v1.0.8 安全分页与可视化渲染工作台（未发布）" not in changelog


def test_readme_promotes_webui_with_explicit_product_boundaries() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (PLUGIN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert readme.index("## WebUI 渲染工作台") < readme.index("## 渲染流程")
    assert "#/plugin-page/astrbot_plugin_latex_render/studio" in readme
    assert "preview API 与 `render_to_image` 工具复用" in readme
    assert "不模拟消息平台的传输与显示行为" in readme
    assert "完整配置仍在 AstrBot 配置页" in readme
    assert "只维护一个 `custom`" in readme
    assert "短引导段会与紧随的公式、表格、代码或列表保持在同一页" in readme
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
    ]:
        assert casual_copy not in readme
        assert casual_copy not in changelog


def test_requirements_only_list_imported_third_party_packages() -> None:
    requirements = (PLUGIN_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "playwright" in requirements
    assert "mistune" in requirements
    assert "Pillow" in requirements
    assert "aiohttp" not in requirements
