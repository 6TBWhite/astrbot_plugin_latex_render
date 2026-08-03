import importlib
from pathlib import Path

import pytest


class FakeInstallProcess:
    returncode = 0

    async def communicate(self):
        return b"", b""


@pytest.mark.asyncio
async def test_ensure_playwright_skips_install_for_expected_executable(
    plugin, plugin_main, monkeypatch, tmp_path
) -> None:
    browser_dir = tmp_path / "chromium_headless_shell-current"
    executable = browser_dir / "chrome-headless-shell" / "chrome-headless-shell.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    async def unexpected_install(*args, **kwargs):
        raise AssertionError("不应重复安装已存在的当前版本浏览器")

    runtime_module = importlib.import_module(
        f"{plugin_main.__package__}.rendering.browser_runtime"
    )
    monkeypatch.setattr(
        plugin.browser, "expected_headless_shell_dir", lambda: browser_dir
    )
    monkeypatch.setattr(
        runtime_module.asyncio, "create_subprocess_exec", unexpected_install
    )

    await plugin.browser.ensure_installed()


@pytest.mark.asyncio
async def test_ensure_playwright_installs_when_only_stale_revision_exists(
    plugin, plugin_main, monkeypatch, tmp_path
) -> None:
    browsers_dir = tmp_path / "playwright_browsers"
    stale_executable = (
        browsers_dir
        / "chromium_headless_shell-old"
        / "chrome-headless-shell-win64"
        / "chrome-headless-shell.exe"
    )
    stale_executable.parent.mkdir(parents=True)
    stale_executable.touch()
    expected_browser_dir = browsers_dir / "chromium_headless_shell-current"
    calls = []

    async def install(*args, **kwargs):
        calls.append(args)
        return FakeInstallProcess()

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browsers_dir))
    runtime_module = importlib.import_module(
        f"{plugin_main.__package__}.rendering.browser_runtime"
    )
    monkeypatch.setattr(
        plugin.browser, "expected_headless_shell_dir", lambda: expected_browser_dir
    )
    monkeypatch.setattr(runtime_module.asyncio, "create_subprocess_exec", install)

    await plugin.browser.ensure_installed()

    assert len(calls) == 1
    assert calls[0][1:] == (
        "-m",
        "playwright",
        "install",
        "chromium-headless-shell",
    )
    assert Path(stale_executable).is_file()
