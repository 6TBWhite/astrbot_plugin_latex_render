import asyncio
import importlib
from types import SimpleNamespace

import pytest

from core.security import sanitize_html_fragment


def test_safe_markdown_removes_executable_html_and_keeps_semantics(plugin_main):
    rendered = plugin_main.markdown_to_html(
        """
# 安全测试
<script>window.pwned = true</script>
<style>body { display: none }</style>
<iframe src="http://127.0.0.1/private"></iframe>
<q onclick="alert(1)">保留对白</q>
<span class="astr-math-inline" onmouseover="alert(2)">\\(x^2\\)</span>
"""
    )

    assert "<script" not in rendered
    assert "<style" not in rendered
    assert "<iframe" not in rendered
    assert "onclick" not in rendered
    assert "onmouseover" not in rendered
    assert "<q>保留对白</q>" in rendered
    assert 'class="astr-math-inline"' in rendered


@pytest.mark.parametrize("language", ["python", "c++", "c#", "foo_bar-2"])
def test_safe_html_keeps_one_valid_code_language_class(language: str) -> None:
    rendered = sanitize_html_fragment(
        f'<pre><code class="ignored language-{language} extra" '
        'onclick="alert(1)">code</code></pre>'
    )

    assert rendered == f'<pre><code class="language-{language}">code</code></pre>'


def test_safe_html_rejects_invalid_or_oversized_code_language_classes() -> None:
    oversized = "x" * 33
    rendered = sanitize_html_fragment(
        '<pre><code class="language-python"><b>safe</b></code></pre>'
        f'<pre><code class="language-{oversized} language-js:evil">plain</code></pre>'
    )

    assert rendered == (
        '<pre><code class="language-python"><b>safe</b></code></pre>'
        "<pre><code>plain</code></pre>"
    )


def test_input_budget_is_rejected_before_browser_work(plugin, plugin_main):
    plugin.config["max_input_chars"] = 100

    with pytest.raises(plugin_main.RenderFailure) as caught:
        asyncio.run(plugin._render_content("x" * 101, "classic", "user-1", False))

    assert caught.value.code == "resource_limit"


def test_full_queue_is_rejected_deterministically(plugin, plugin_main):
    plugin.config["max_concurrent_renders"] = 1
    plugin.config["max_queue_size"] = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_inner(*args, **kwargs):
        entered.set()
        await release.wait()
        return plugin_main.RenderResult(images=[object()], template="classic")

    plugin._render_content_inner = slow_inner

    async def scenario():
        first = asyncio.create_task(
            plugin._render_content("first", "classic", "user-1", False)
        )
        await entered.wait()
        with pytest.raises(plugin_main.RenderFailure) as caught:
            await plugin._render_content("second", "classic", "user-2", False)
        assert caught.value.code == "queue_full"
        release.set()
        await first

    asyncio.run(scenario())


def test_network_policy_blocks_remote_and_file_urls(plugin_main):
    renderer = importlib.import_module(f"{plugin_main.__package__}.core.renderer")

    class FakePage:
        def __init__(self):
            self.handler = None

        async def route(self, pattern, handler):
            assert pattern == "**/*"
            self.handler = handler

    class FakeRoute:
        def __init__(self, url):
            self.request = SimpleNamespace(url=url)
            self.action = ""

        async def abort(self):
            self.action = "abort"

        async def continue_(self):
            self.action = "continue"

    async def scenario():
        page = FakePage()
        await renderer._install_network_policy(page, allow_remote_assets=False)
        routes = [
            FakeRoute("https://example.com/a.png"),
            FakeRoute("http://127.0.0.1/private"),
            FakeRoute("file:///etc/passwd"),
            FakeRoute("data:image/png;base64,AAAA"),
        ]
        for route in routes:
            await page.handler(route)
        return [route.action for route in routes]

    assert asyncio.run(scenario()) == ["abort", "abort", "abort", "continue"]
