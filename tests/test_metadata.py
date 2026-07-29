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
    assert metadata["version"] == version_match.group(1)
    assert metadata["type"] == "star"
    assert metadata["category"] == "工具"
    assert metadata["branch"] == "master"
    assert metadata["license"] == "MIT"
    assert metadata["short_desc"].strip()
    assert metadata["desc"].strip()
    assert 3 <= len(metadata["tags"]) <= 6
    assert metadata["requirements"] == []


def test_requirements_only_list_imported_third_party_packages() -> None:
    requirements = (PLUGIN_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "playwright" in requirements
    assert "mistune" in requirements
    assert "Pillow" in requirements
    assert "aiohttp" not in requirements
