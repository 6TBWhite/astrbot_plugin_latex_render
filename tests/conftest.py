import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "astrbot_plugin_latex_render_under_test"


def _load_plugin_package():
    package = sys.modules.get(PACKAGE_NAME)
    if package is None:
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME,
            PLUGIN_ROOT / "__init__.py",
            submodule_search_locations=[str(PLUGIN_ROOT)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("无法加载插件包")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{PACKAGE_NAME}.main")


@pytest.fixture(scope="session")
def plugin_main():
    return _load_plugin_package()


@pytest.fixture()
def plugin(plugin_main, tmp_path):
    instance = object.__new__(plugin_main.LatexRenderPlugin)
    instance.config = {
        "default_template": "",
        "enable_markdown": True,
        "enable_math": True,
        "enable_hidden_ctx_buffer": False,
        "inject_template_prompts": False,
        "render_width": 600,
        "render_scale": 2,
    }
    instance.DATA_DIR = str(tmp_path)
    instance.IMAGE_CACHE_DIR = str(tmp_path / "latex_cache")
    Path(instance.IMAGE_CACHE_DIR).mkdir()
    instance.template_mgr = plugin_main.TemplateManager(str(PLUGIN_ROOT / "templates"))
    instance.template_mgr.update_template_id_map()
    instance.user_default_template = {}
    instance._hidden_ctx_buffer = {}
    instance._bg_asset_cache = {}
    instance._bg_image_size = None
    instance._bg_round_robin_index = 0
    instance.gif_duration = 3.0
    instance.gif_fps = 15
    instance._schedule_delete = lambda *paths: None
    return instance


@dataclass
class FakeResult:
    kind: str
    payload: object


class FakeEvent:
    def __init__(
        self,
        message_str: str = "",
        user_id: str = "user-1",
        unified_msg_origin: str = "platform:message_type:session-1",
    ):
        self.message_str = message_str
        self._user_id = user_id
        self.unified_msg_origin = unified_msg_origin
        self.sent: list[FakeResult] = []

    def get_sender_id(self) -> str:
        return self._user_id

    def plain_result(self, text: str) -> FakeResult:
        return FakeResult("plain", text)

    def chain_result(self, chain: list) -> FakeResult:
        return FakeResult("chain", chain)

    async def send(self, result: FakeResult) -> None:
        self.sent.append(result)


@pytest.fixture()
def fake_event_type():
    return FakeEvent


async def collect_async_generator(generator) -> list:
    return [item async for item in generator]


@pytest.fixture()
def collect_results():
    return collect_async_generator
