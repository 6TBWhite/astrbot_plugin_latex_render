# main.py
# 插件入口：LatexRenderPlugin 主类 + 命令 + 事件处理

import asyncio
import base64
import os
import random
import re
import sys
import time
import uuid

from PIL import Image as PILImage

# 将插件目录加入搜索路径，使同目录模块可导入
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

import text_processing as _text_processing
from renderer import close_browser, html_to_image_playwright, init_browser
from template_manager import TemplateManager
from text_processing import (
    markdown_to_html,
    nl2br,
    preserve_newlines,
)

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.star_tools import StarTools


def _contains_math(content: str) -> bool:
    """Backward-compatible math detection so old cached modules won't break startup."""
    detector = getattr(_text_processing, "contains_math", None)
    if callable(detector):
        return detector(content)

    if not content:
        return False

    return bool(
        re.search(r"(?<!\\)\$(?!\$).+?(?<!\\)\$(?!\$)", content, re.DOTALL)
        or re.search(r"(?<!\\)\$\$[\s\S]+?(?<!\\)\$\$", content, re.DOTALL)
        or re.search(r"\\\(.+?\\\)", content, re.DOTALL)
        or re.search(r"\\\[[\s\S]+?\\\]", content, re.DOTALL)
        or re.search(r"\\begin\{([a-zA-Z*]+)\}[\s\S]+?\\end\{\1\}", content, re.DOTALL)
    )


@register(
    "astrbot_plugin_latex_render",
    "6TBWhite & Para",
    "LLM能够主动调用的图片渲染工具，可支持文本、LaTeX/Markdown 内容，支持本地字体与自定义模板。",
    "1.0.1",
)
class LatexRenderPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.DATA_DIR = os.path.normpath(StarTools.get_data_dir())
        self.IMAGE_CACHE_DIR = os.path.join(self.DATA_DIR, "latex_cache")

        # 模板管理器
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.template_mgr = TemplateManager(template_dir)

        # 用户默认模板设置（用户ID -> 模板名）
        self.user_default_template: dict[str, str] = {}

        # 隐藏上下文缓冲（chat_id -> [{content, ts}]），发图时原文暂存，不进消息链
        self._hidden_ctx_buffer: dict[str, list[dict]] = {}

        # GIF 配置
        self.gif_duration = config.get("gif_duration", 3.0)
        self.gif_fps = config.get("gif_fps", 15)
        # 背景图缓存（按相对路径缓存 data URL 和尺寸）
        self._bg_asset_cache: dict[str, tuple[str, tuple[int, int]]] = {}
        self._bg_image_size: tuple[int, int] | None = None
        self._bg_round_robin_index = 0

    # classic 模板可配置的 CSS 变量（配置键、CSS 变量名、单位）
    _CLASSIC_STYLE_VARS = [
        ("classic_body_padding", "--classic-body-padding", "px"),
        ("classic_page_padding_y", "--classic-page-padding-y", "px"),
        ("classic_page_padding_x", "--classic-page-padding-x", "px"),
        ("classic_font_size", "--classic-font-size", "px"),
        ("classic_line_height", "--classic-line-height", ""),
        ("classic_h1_size", "--classic-h1-size", "px"),
        ("classic_h2_size", "--classic-h2-size", "px"),
        ("classic_h3_size", "--classic-h3-size", "px"),
    ]

    # ==================== 生命周期 ====================

    async def initialize(self):
        try:
            os.makedirs(self.IMAGE_CACHE_DIR, exist_ok=True)
            plugin_data_dir = os.path.normpath(StarTools.get_data_dir("astrbot_plugin_latex_render"))
            playwright_browsers_dir = os.path.join(plugin_data_dir, "playwright_browsers")
            os.makedirs(playwright_browsers_dir, exist_ok=True)
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = playwright_browsers_dir
            logger.info(f"HTML渲染插件: Playwright 浏览器路径 → {playwright_browsers_dir}")
            self._cleanup_cache()
            await self.template_mgr.load_templates()
            self._refresh_template_schema_options()
            self._require_available_templates()
            self.template_mgr.update_template_id_map()
            await self._ensure_playwright()
            # 预启动浏览器实例（后续渲染复用，避免首次渲染等待）
            await init_browser()
            if self.config.get("enable_hidden_ctx_buffer", True):
                logger.warning("[实验性] 隐藏上下文缓冲区已开启。此功能仅对超长推导链（>20轮）调试有用，普通会话建议关闭以节省上下文空间")
            logger.info("HTML 渲染插件初始化完成")
        except Exception as e:
            logger.error(f"HTML 渲染插件初始化失败: {e}")
            if isinstance(e, FileNotFoundError):
                raise

    async def _ensure_playwright(self):
        browsers_dir = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
        if browsers_dir and os.path.isdir(browsers_dir):
            has_chromium = any(
                name.lower().startswith("chromium") for name in os.listdir(browsers_dir)
            )
            if has_chromium:
                logger.info("HTML渲染插件: Playwright Chromium 已存在，跳过安装")
                return

        logger.info("HTML渲染插件: 检查 Playwright 依赖...")
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "playwright", "install", "chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                logger.error(f"Playwright Chromium 安装失败: {stderr.decode('utf-8', errors='ignore')}")
        except Exception as e:
            logger.error(f"执行命令失败: {e}")

    async def terminate(self):
        await close_browser()
        logger.info("HTML 渲染插件已停止")

    def _get_background_image_strategy(self) -> str:
            strategy = str(self.config.get("background_image_strategy", "fixed") or "fixed").strip().lower()
            if strategy not in {"fixed", "round_robin", "random"}:
                return "fixed"
            return strategy

    def _select_background_image(self) -> str:
            configured_image = str(self.config.get("background_image", "") or "").strip()
            strategy = self._get_background_image_strategy()
            available_images = self._get_available_background_images()

            if strategy == "fixed":
                return configured_image

            if not available_images:
                return ""

            if strategy == "random":
                return random.choice(available_images)

            image_path = available_images[self._bg_round_robin_index % len(available_images)]
            self._bg_round_robin_index += 1
            return image_path

    def _get_bg_data_url(self) -> str:
            """按配置选择背景图片并转为 base64 Data URL。"""
            bg_config = self._select_background_image()
            if not bg_config:
                self._bg_image_size = None
                return ""

            bg_path = os.path.join(_PLUGIN_DIR, bg_config)
            if not os.path.isfile(bg_path):
                logger.warning(f"[HTML渲染] 背景图片不存在: {bg_path}，将使用默认背景")
                self._bg_image_size = None
                return ""

            cached_asset = self._bg_asset_cache.get(bg_config)
            if cached_asset:
                self._bg_image_size = cached_asset[1]
                return cached_asset[0]

            try:
                ext = os.path.splitext(bg_path)[1].lower()
                mime_map = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                }
                mime = mime_map.get(ext, "image/png")
                with PILImage.open(bg_path) as img:
                    image_size = (max(1, img.width), max(1, img.height))
                with open(bg_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                data_url = f"data:{mime};base64,{encoded}"
                self._bg_asset_cache[bg_config] = (data_url, image_size)
                self._bg_image_size = image_size
                logger.info(f"[HTML渲染] 背景图片已加载: {bg_config} ({mime})")
            except Exception as e:
                logger.warning(f"[HTML渲染] 读取背景图片失败: {e}")
                self._bg_image_size = None
                return ""

            return data_url

    def _inject_math_assets(self, html_content: str) -> str:
            """为包含数学公式的页面注入 MathJax 资源，优先加载本地副本。"""
            if 'id="astrbot-mathjax-script"' in html_content or "data-astrbot-mathjax-loader" in html_content:
                return html_content

            if getattr(self, "_mathjax_src", None) is None:
                _plugin_dir = os.path.dirname(os.path.abspath(__file__))
                _mathjax_path = os.path.join(_plugin_dir, "mathjax-tex-svg.js")
                if os.path.exists(_mathjax_path):
                    try:
                        with open(_mathjax_path, encoding="utf-8") as _f:
                            self._mathjax_src = _f.read()
                        logger.info(f"[HTML 渲染] 已加载本地 MathJax: {_mathjax_path} ({len(self._mathjax_src)} 字节)")
                    except Exception as _e:
                        logger.warning(f"[HTML 渲染] 读取本地 MathJax 失败: {_e}")
                        self._mathjax_src = ""
                else:
                    self._mathjax_src = ""
            _mathjax_src = self._mathjax_src

            if _mathjax_src:
                # 内嵌本地副本，避免外网 CDN 超时与 file:// 安全限制
                # 使用 base64 编码，防止 JS 中的 </script> 等内容打断 HTML 解析
                _mathjax_b64 = base64.b64encode(_mathjax_src.encode("utf-8")).decode("ascii")
                mathjax_loader = f"""
<script data-astrbot-mathjax-loader>
(function(){{
  var code = atob({_mathjax_b64!r});
  var s = document.createElement('script');
  s.id = 'astrbot-mathjax-script';
  s.type = 'text/javascript';
  s.textContent = code;
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', function(){{ document.head.appendChild(s); }});
  }} else {{
    document.head.appendChild(s);
  }}
}})();
</script>
"""
            else:
                mathjax_loader = """
<script
  id="astrbot-mathjax-script"
  data-astrbot-mathjax-loader
  defer
  src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"
  onerror="window.__ASTR_MATH_READY__ = true;"
></script>
"""

            math_assets = """
<style>
.astr-math-inline,
.astr-math-block {
  max-width: 100%;
}
.astr-math-block {
  display: block;
  margin: 0.9em 0;
  overflow-x: auto;
  overflow-y: hidden;
  text-align: center;
}
mjx-container,
mjx-container * {
  word-break: normal !important;
  overflow-wrap: normal !important;
}
mjx-container[jax="SVG"] {
  max-width: 100%;
}
.astr-math-block mjx-container[jax="SVG"] {
  display: inline-block !important;
  margin: 0 auto !important;
}
</style>
<script>
window.__ASTR_MATH_READY__ = false;
window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
    processEscapes: true,
    processEnvironments: true,
    packages: {'[+]': ['ams', 'noerrors', 'noundefined']}
  },
  svg: {
    fontCache: 'global'
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
  },
  startup: {
    pageReady: () => MathJax.startup.defaultPageReady().then(() => {
      window.__ASTR_MATH_READY__ = true;
    })
  }
};
</script>
""" + mathjax_loader

            if "</head>" in html_content:
                return html_content.replace("</head>", math_assets + "</head>", 1)

            return math_assets + html_content

    def _get_background_render_mode(self) -> str:
            mode = str(self.config.get("background_render_mode", "ambient") or "ambient").strip().lower()
            if mode not in {"ambient", "watermark"}:
                return "ambient"
            return mode

    def _get_background_opacity(self, render_mode: str) -> float:
            default_opacity = 0.17 if render_mode == "watermark" else 0.22
            raw_value = self.config.get("background_opacity", default_opacity)
            try:
                opacity = float(raw_value)
            except (TypeError, ValueError):
                return default_opacity
            return max(0.0, min(1.0, opacity))

    def _get_background_aspect_ratio(self) -> str:
            if self._bg_image_size and self._bg_image_size[0] > 0 and self._bg_image_size[1] > 0:
                return f"{self._bg_image_size[0]} / {self._bg_image_size[1]}"
            return "1 / 1"

    def _inject_background_image(self, html_content: str, bg_data_url: str, render_mode: str) -> str:
            """Inject the configured background as a real backdrop layer."""
            if not bg_data_url or 'id="astrbot-custom-bg-style"' in html_content:
                return html_content

            aspect_ratio = self._get_background_aspect_ratio()
            opacity = self._get_background_opacity(render_mode)
            if render_mode == "watermark":
                bg_assets = f"""
<style id="astrbot-custom-bg-style">
html {{
  background: transparent !important;
}}
body {{
  position: relative !important;
  background: transparent !important;
}}
.content {{
  position: relative !important;
  isolation: isolate !important;
  z-index: 0;
}}
.content::before {{
  content: "";
  position: absolute;
  top: 18px;
  left: 50%;
  width: calc(100% + 20px);
  max-width: calc(100% + 20px);
  aspect-ratio: {aspect_ratio};
  height: auto;
  transform: translateX(-50%) scale(1.015);
  transform-origin: center top;
  z-index: 0;
  pointer-events: none;
  background-image: url("{bg_data_url}");
  background-size: 100% auto;
  background-position: center top;
  background-repeat: no-repeat;
  opacity: {opacity};
  filter: saturate(0.92) contrast(0.97);
  mix-blend-mode: multiply;
}}
.content > * {{
  position: relative;
  z-index: 1;
}}
</style>
"""
            else:
                bg_assets = f"""
<style id="astrbot-custom-bg-style">
html {{
  background: transparent !important;
}}
body {{
  position: relative !important;
  isolation: isolate !important;
  background: transparent !important;
}}
body::before {{
  content: "";
  position: absolute;
  inset: 0;
  z-index: -2;
  pointer-events: none;
  background-image: url("{bg_data_url}");
  background-size: 102% auto;
  background-position: center top;
  background-repeat: repeat-y;
  background-attachment: scroll;
  opacity: {opacity};
  filter: blur(6px) saturate(0.95);
  transform: scale(1.015);
  transform-origin: center top;
}}
body::after {{
  content: "";
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.20), rgba(255,255,255,0.12)),
    radial-gradient(circle at top, rgba(255,255,255,0.16), rgba(255,255,255,0.03) 55%);
}}
body > * {{
  position: relative;
  z-index: 1;
}}
</style>
"""

            if "</head>" in html_content:
                return html_content.replace("</head>", bg_assets + "</head>", 1)

            return bg_assets + html_content

    def _cleanup_cache(self, max_age_seconds: int = 300):
        """清理缓存目录中的过期文件"""
        import time
        now = time.time()
        count = 0
        try:
            for f in os.listdir(self.IMAGE_CACHE_DIR):
                fp = os.path.join(self.IMAGE_CACHE_DIR, f)
                if os.path.isfile(fp) and (now - os.path.getmtime(fp)) > max_age_seconds:
                    os.remove(fp)
                    count += 1
            if count:
                logger.info(f"[HTML渲染] 已清理 {count} 个缓存文件")
        except Exception as e:
            logger.warning(f"[HTML渲染] 清理缓存失败: {e}")

    def _schedule_delete(self, *paths):
        """延迟删除文件（给消息发送留足时间，多图模式下图片生成耗时较长）"""
        async def _delete():
            await asyncio.sleep(300)
            for p in paths:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
        asyncio.create_task(_delete())

    # ==================== 工具方法 ====================

    def _get_user_id(self, event: AstrMessageEvent) -> str:
        try:
            if hasattr(event, "get_sender_id") and callable(event.get_sender_id):
                return str(event.get_sender_id())
            if hasattr(event, "sender") and hasattr(event.sender, "user_id"):
                return str(event.sender.user_id)
            return str(event.unified_msg_origin)
        except Exception:
            return "default_user"

    def _refresh_template_schema_options(self):
        schema = getattr(self.config, "schema", None)
        if not isinstance(schema, dict):
            return

        templates = self._get_available_templates()
        template_options = [""] + templates

        field_labels = {
            "default_template": ["自动使用第一个可用模板"] + templates,
        }

        for field_name, empty_label in field_labels.items():
            field_meta = schema.get(field_name)
            if not isinstance(field_meta, dict):
                continue
            field_meta["options"] = template_options
            field_meta["enum"] = template_options
            field_meta["labels"] = empty_label

        bg_field_meta = schema.get("background_image")
        if isinstance(bg_field_meta, dict):
            background_images = self._get_available_background_images()
            bg_field_meta["options"] = [""] + background_images
            bg_field_meta["enum"] = [""] + background_images
            bg_field_meta["labels"] = ["不使用自定义背景"] + background_images

    def _get_available_templates(self) -> list[str]:
        getter = getattr(self.template_mgr, "get_available_templates", None)
        if callable(getter):
            templates = getter()
            if isinstance(templates, list):
                return templates
        return []

    def _get_available_background_images(self) -> list[str]:
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        results: list[str] = []

        for root, _, files in os.walk(_PLUGIN_DIR):
            for filename in files:
                if os.path.splitext(filename)[1].lower() not in image_exts:
                    continue
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, _PLUGIN_DIR)
                results.append(rel_path.replace("\\", "/"))

        return sorted(set(results))

    def _require_available_templates(self) -> list[str]:
        getter = getattr(self.template_mgr, "require_available_templates", None)
        if callable(getter):
            return getter()

        templates = self._get_available_templates()
        if templates:
            return templates

        template_dir = getattr(self.template_mgr, "TEMPLATE_DIR", os.path.join(_PLUGIN_DIR, "templates"))
        raise FileNotFoundError(
            f"未找到任何模板文件，请先在 {template_dir} 中放入至少一个 .html 模板"
        )

    def _has_template(self, template_name: str | None) -> bool:
        if not template_name:
            return False

        checker = getattr(self.template_mgr, "has_template", None)
        if callable(checker):
            return bool(checker(template_name))

        return template_name in self._get_available_templates()

    def _get_configured_template_name(self, key: str) -> str | None:
        value = self.config.get(key, "")
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    def _resolve_existing_template(self, template_name: str | None, source: str) -> str | None:
        if not template_name:
            return None
        if self._has_template(template_name):
            return template_name
        raise ValueError(f"{source} 指向的模板不存在: {template_name}")

    def _get_default_template(self, user_id: str | None = None) -> str:
        available = self._require_available_templates()

        if user_id:
            user_template = self.user_default_template.get(user_id)
            if user_template and self._has_template(user_template):
                return user_template
            if user_template:
                self.user_default_template.pop(user_id, None)
                logger.warning(
                    f"[HTML渲染] 用户 {user_id} 的默认模板不存在，已清除失效配置: {user_template}"
                )

        configured_default = self._get_configured_template_name("default_template")
        resolved_default = self._resolve_existing_template(
            configured_default,
            "default_template",
        )
        if resolved_default:
            return resolved_default

        return available[0]

    def _select_template(self, content: str, specified_template: str | None = None, user_id: str | None = None) -> str:
        available = self._require_available_templates()

        if specified_template:
            return self._resolve_existing_template(specified_template, "specified template")

        if user_id and user_id in self.user_default_template:
            user_tpl = self.user_default_template[user_id]
            if user_tpl in available:
                return user_tpl
            self.user_default_template.pop(user_id, None)
            logger.warning(f"[HTML渲染] 已移除失效的用户模板配置: {user_tpl}")

        return self._get_default_template(user_id)

    def _inject_template_vars(self, html: str, template_name: str) -> str:
        """为指定模板注入可配置 CSS 变量（当前仅 classic 模板支持）。"""
        if template_name != "classic":
            return html

        lines: list[str] = []
        for config_key, var_name, unit in self._CLASSIC_STYLE_VARS:
            value = self.config.get(config_key)
            if value is None:
                continue
            try:
                # 简单校验，避免输入格式异常时直接抛出
                _ = float(value)
            except (TypeError, ValueError):
                continue
            lines.append(f"    {var_name}: {value}{unit};")

        if not lines:
            return html

        style_block = (
            '<style id="astrbot-classic-vars">\n:root {\n'
            + "\n".join(lines)
            + "\n}\n</style>"
        )

        head_end = html.lower().rfind("</head>")
        if head_end != -1:
            return html[:head_end] + style_block + "\n" + html[head_end:]
        # 如果没有 head，直接拼在最前面
        return style_block + "\n" + html

    def _apply_template(self, content: str, template_name: str, is_raw_html: bool = False) -> str:
        """
        应用模板。
        :param is_raw_html: 若为 True，跳过 markdown/nl2br 处理，直接嵌入原始 HTML
        """
        template = self.template_mgr.load_template(template_name)

        if is_raw_html:
            # 内容自带完整 HTML+CSS，不做任何文本处理
            html = template.replace("{{content}}", content)
            return self._inject_template_vars(html, template_name)

        if self.config.get("enable_markdown", True):
            content = markdown_to_html(content)
            html = template.replace("{{content}}", content)
            return self._inject_template_vars(html, template_name)
        else:
            content = preserve_newlines(content)

        content = nl2br(content)
        html = template.replace("{{content}}", content)
        return self._inject_template_vars(html, template_name)

    # ==================== 渲染核心 ====================

    async def _render_content(self, content: str, specified_template: str | None, user_id: str | None = None, is_gif: bool = False):
        """
        执行渲染。
        GIF 模式返回 List[Image]（静态图 + GIF），普通模式返回单个 Image。
        失败返回 None。
        """
        try:
            template_name = self._select_template(content, specified_template, user_id)
            logger.debug(f"HTML渲染: 使用模板 {template_name}, GIF模式: {is_gif}")

            # 检测内容是否自带 <style> 标签，若有则为完整 HTML，跳过文本处理
            has_own_style = bool(re.search(r"<style\b", content, re.IGNORECASE))
            full_html = self._apply_template(content, template_name, is_raw_html=has_own_style)
            if self.config.get("enable_math", True) and _contains_math(content):
                full_html = self._inject_math_assets(full_html)
            # 注入自定义背景图（转为 base64 内嵌，避免 Playwright 沙箱限制）
            bg_data_url = self._get_bg_data_url()
            if bg_data_url:
                bg_render_mode = self._get_background_render_mode()
                full_html = self._inject_background_image(full_html, bg_data_url, bg_render_mode)
            # GIF 模式始终用 .jpg 作为主输出（JPEG体积远小于PNG，渲染更快）
            filename_base = f"render_{uuid.uuid4().hex[:12]}"
            output_path = os.path.join(self.IMAGE_CACHE_DIR, f"{filename_base}.jpg")

            width = self.config.get("render_width", 600)
            if is_gif:
                scale = self.config.get("gif_scale", self.config.get("render_scale", 2))
            else:
                scale = self.config.get("render_scale", 2)

            success = await html_to_image_playwright(
                html_content=full_html,
                output_image_path=output_path,
                scale=scale,
                width=width,
                is_gif=is_gif,
                duration=self.gif_duration,
                fps=self.gif_fps,
            )

            if not success:
                return None

            if is_gif:
                results = []
                delete_paths = []
                if os.path.exists(output_path):
                    results.append(Image.fromFileSystem(output_path))
                    delete_paths.append(output_path)
                gif_path = os.path.join(self.IMAGE_CACHE_DIR, f"{filename_base}.gif")
                if os.path.exists(gif_path):
                    results.append(Image.fromFileSystem(gif_path))
                    delete_paths.append(gif_path)
                if delete_paths:
                    self._schedule_delete(*delete_paths)
                return results if results else None
            else:
                if os.path.exists(output_path):
                    img = Image.fromFileSystem(output_path)
                    self._schedule_delete(output_path)
                    return img
                return None
        except Exception as e:
            logger.error(f"渲染过程异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    # ==================== 命令 ====================

    @filter.command("测试", aliases=["test"])
    async def cmd_test_render(self, event: AstrMessageEvent):
        full_msg = event.message_str.strip()
        full_msg = re.sub(r"\[At:\d+\]\s*", "", full_msg).strip()
        parts = full_msg.split(None, 1)
        text = parts[1].strip() if len(parts) > 1 else ""

        user_id = self._get_user_id(event)

        if not text:
            try:
                tpl = self._get_default_template(user_id)
            except Exception as e:
                yield event.plain_result(f"渲染失败：{e}")
                return
            text = TemplateManager.get_default_test_content(tpl)
        elif text.strip().lower() == "gif":
            text = TemplateManager.get_gif_test_content()
            logger.info("[HTML渲染] 使用 GIF 弹幕测试内容")

        try:
            tpl = self._get_default_template(user_id)
            image = await self._render_content(text, tpl, user_id, False)
        except Exception as e:
            yield event.plain_result(f"渲染失败：{e}")
            return
        self._push_hidden_ctx(event, text)

        if image:
            if isinstance(image, list):
                yield event.chain_result(image)
            else:
                yield event.chain_result([image])
        else:
            yield event.plain_result("❌ 渲染失败，请检查日志获取详细信息")

    @filter.command("切换", aliases=["switch"])
    async def cmd_switch_template(self, event: AstrMessageEvent):
        full_msg = event.message_str.strip()
        full_msg = re.sub(r"\[At:\d+\]\s*", "", full_msg).strip()
        parts = full_msg.split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        user_id = self._get_user_id(event)
        try:
            current = self._get_default_template(user_id)
        except Exception:
            current = "未设置"
        available = self._get_available_templates()
        if not available:
            yield event.plain_result(
                f"渲染失败：未找到任何模板文件，请先在 {self.template_mgr.TEMPLATE_DIR} 中放入至少一个 .html 模板"
            )
            return

        if not arg:
            yield event.plain_result(
                f"🔄 切换渲染模板\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"用法: /切换 <模板名或ID>\n"
                f"当前模板: {current}\n\n"
                f"示例:\n  /切换 <模板名>\n  /切换 1\n\n"
                f"使用 /查看 查看可用模板列表"
            )
            return

        template_name = None
        try:
            tid = int(arg)
            template_name = self.template_mgr.template_id_map.get(tid)
        except ValueError:
            pass

        if not template_name:
            if arg in available:
                template_name = arg

        if not template_name:
            yield event.plain_result(f"❌ 未找到模板: {arg}\n\n请使用 /查看 查看可用模板列表")
            return

        self.user_default_template[user_id] = template_name
        logger.info(f"[HTML渲染] 用户 {user_id} 切换默认模板: {current} -> {template_name}")
        yield event.plain_result(f"✅ 已切换默认模板为: {template_name}")
    @filter.command("探针gif", aliases=["probegif"])
    async def cmd_probe_gif(self, event: AstrMessageEvent):
        """诊断 GIF 渲染问题：截取多帧并保存为独立图片"""
        from playwright.async_api import async_playwright
        from template_manager import TemplateManager

        html_content = TemplateManager.get_gif_test_content()
        # 移除 <render gif> 标签，只保留 HTML
        html_content = re.sub(r"<render[^>]*>", "", html_content)
        html_content = re.sub(r"</render>", "", html_content)

        yield event.plain_result("🔍 开始 GIF 渲染探针，请稍候...")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context(
                    device_scale_factor=2,
                    viewport={"width": 600, "height": 800},
                )
                page = await context.new_page()
                await page.set_content(html_content, wait_until="networkidle")

                # 展开视口
                content_h = await page.evaluate("document.body.scrollHeight")
                await page.set_viewport_size({"width": 600, "height": max(content_h, 200)})
                await asyncio.sleep(1.0)

                # 检查弹幕元素是否存在
                danmu_count = await page.evaluate("document.querySelectorAll('.danmu-line').length")
                logger.info(f"[探针] 弹幕元素数量: {danmu_count}")

                # 检查弹幕元素的实际位置和样式
                danmu_info = await page.evaluate("""() => {
                    const items = document.querySelectorAll('.danmu-line');
                    return Array.from(items).map((el, i) => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return {
                            index: i,
                            text: el.textContent.substring(0, 20),
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            visible: rect.width > 0 && rect.height > 0,
                            animation: style.animation,
                            animationPlayState: style.animationPlayState,
                            transform: style.transform,
                            left: style.left,
                            opacity: style.opacity,
                            display: style.display,
                        };
                    });
                }""")

                for info in danmu_info:
                    logger.info(f"[探针] 弹幕#{info['index']}: "
                               f"text='{info['text']}' "
                               f"pos=({info['x']},{info['y']}) "
                               f"size={info['width']}x{info['height']} "
                               f"visible={info['visible']} "
                               f"animation='{info['animation']}' "
                               f"state='{info['animationPlayState']}' "
                               f"transform='{info['transform']}' "
                               f"left='{info['left']}'")

                # 截取 3 帧，间隔 1 秒
                probe_images = []
                for i in range(3):
                    shot_path = os.path.join(self.IMAGE_CACHE_DIR, f"probe_frame_{i}.png")
                    await page.screenshot(path=shot_path, full_page=True)
                    probe_images.append(Image.fromFileSystem(shot_path))
                    logger.info(f"[探针] 已截取第 {i+1} 帧")
                    if i < 2:
                        await asyncio.sleep(1.0)

                await browser.close()

            # 发送 3 帧截图
            result_chain = [Plain(f"🔍 探针结果：检测到 {danmu_count} 个弹幕元素\n详细信息请查看控制台日志\n\n以下是间隔1秒的3帧截图：")]
            result_chain.extend(probe_images)
            yield event.chain_result(result_chain)

        except Exception as e:
            logger.error(f"[探针] 失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield event.plain_result(f"❌ 探针失败: {e}")
    @filter.command("预览模板", aliases=["previewtpl", "tplpreview"])
    async def cmd_preview_template(self, event: AstrMessageEvent):
        full_msg = event.message_str.strip()
        full_msg = re.sub(r"\[At:\d+\]\s*", "", full_msg).strip()
        parts = full_msg.split(None, 2)
        arg = parts[1].strip() if len(parts) > 1 else ""
        text = parts[2].strip() if len(parts) > 2 else ""

        if not arg:
            yield event.plain_result("📖 用法: /预览模板 <模板名或ID> [文本]\n示例: /预览模板 <模板名> 晚风穿过旧街，灯火一盏盏亮起来。")
            return

        available = self._get_available_templates()
        if not available:
            yield event.plain_result(
                f"渲染失败：未找到任何模板文件，请先在 {self.template_mgr.TEMPLATE_DIR} 中放入至少一个 .html 模板"
            )
            return

        self.template_mgr.update_template_id_map()
        template_name = None
        try:
            tid = int(arg)
            template_name = self.template_mgr.template_id_map.get(tid)
        except ValueError:
            pass
        if not template_name and arg in available:
            template_name = arg
        if not template_name:
            yield event.plain_result(f"❌ 未找到模板: {arg}")
            return

        user_id = self._get_user_id(event)
        if not text:
            text = TemplateManager.get_default_test_content(template_name)
        try:
            image = await self._render_content(text, template_name, user_id, False)
        except Exception as e:
            yield event.plain_result(f"渲染失败：{e}")
            return
        self._push_hidden_ctx(event, text)

        if image:
            chain = [Plain(f"🖼️ 模板预览: {template_name}")]
            if isinstance(image, list):
                chain.extend(image)
            else:
                chain.append(image)
            yield event.chain_result(chain)
        else:
            yield event.plain_result("❌ 模板预览失败，请检查日志")

    @filter.command("查看", aliases=["templates"])
    async def cmd_list_templates(self, event: AstrMessageEvent):
        available = self._get_available_templates()
        if not available:
            yield event.plain_result("❌ 当前没有可用的模板")
            return

        self.template_mgr.update_template_id_map()
        user_id = self._get_user_id(event)
        try:
            current = self._get_default_template(user_id)
        except Exception:
            current = "未设置"

        lines = ["📋 可用模板列表", "━━━━━━━━━━━━━━━━━━", ""]
        for idx in sorted(self.template_mgr.template_id_map.keys()):
            name = self.template_mgr.template_id_map[idx]
            marker = " ← 当前" if name == current else ""
            lines.append(f"  {idx}. {name}{marker}")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("使用方法:")
        lines.append("  /切换 <ID或名称>      切换默认模板")
        lines.append("  /测试 <文本>          测试渲染效果")
        lines.append("  /预览模板 <ID或名称> [文本]  临时预览指定模板")

        yield event.plain_result("\n".join(lines))

    # ==================== LLM 工具 ====================

    @filter.llm_tool(name="render_to_image")
    async def render_to_image_tool(
        self,
        event: AstrMessageEvent,
        content: str = "",
        template: str = "",
    ):
        """将完整文本内容渲染为图片并发送给用户。

⚠️ 调用前必须先在 content 中写好所有要展示的完整文本（整段回复），content 不可为空，否则会报错。
支持 Markdown 语法和 LaTeX 公式（$行内$ / $$行间$$）。

适用场景：讲解题目、展示数学公式/方程、制作表格、代码展示、结构化知识整理等。

Args:
    content (string): 必填，不可为空。将要渲染成图片的完整文本内容，直接写 Markdown + LaTeX 公式。不要包裹 <render> 标签或代码块。
    template (string): 可选。classic（讲题排版，默认）或 novel（小说风格）。不指定则使用用户默认模板。
    """
        if not content or not content.strip():
            yield "⚠️ 内容不能为空，请提供需要渲染的 Markdown 文本。"
            return
        user_id = self._get_user_id(event)
        tpl = template.strip() if template and template.strip() else None

        # 原文暂存进隐藏上下文缓冲区，不进消息链（仅发图）
        if content and self.config.get("enable_hidden_ctx_buffer", True):
            self._push_hidden_ctx(event, content)

        try:
            image = await self._render_content(content, tpl, user_id, False)
        except Exception as e:
            logger.error(f"[HTML渲染] render_to_image 工具渲染失败: {e}")
            yield f"渲染失败：{e}"
            return

        if image:
            if isinstance(image, list):
                await event.send(event.chain_result(image))
            else:
                await event.send(event.chain_result([image]))
            yield "图片已渲染并发送给用户。可对图片内容进行简要解说。"
        else:
            yield "渲染失败，请检查内容格式后重试。"

    # ==================== 隐藏上下文缓冲 ====================

    def _push_hidden_ctx(self, event: AstrMessageEvent, content: str, max_per_chat: int = 3):
        """⚠️ [实验性功能] 发图时原文暂存进缓冲区，不进消息链（用户那边看图，LLM 看文）。
        仅对超长推导链（>20轮）调试有用，普通会话建议关闭。
        """
        if not self.config.get("enable_hidden_ctx_buffer", True):
            logger.warning("[实验性] 隐藏上下文缓冲区已关闭（enable_hidden_ctx_buffer=False），不再暂存和注入")
            return
        if not content or not content.strip():
            return
        chat_id = self._get_user_id(event)
        if not chat_id:
            return
        buf = self._hidden_ctx_buffer.setdefault(chat_id, [])
        cleaned = content.strip()
        buf.append({"content": cleaned, "ts": time.time()})
        logger.info(f"[实验性][Hidden] 暂存 {len(cleaned)} 字符到缓冲区 (深度 {len(buf)}/{max_per_chat})")
        while len(buf) > max_per_chat:
            evicted = buf.pop(0)
            logger.info(f"[实验性][Hidden] 缓冲区已满，移除最早条目 ({len(evicted['content'])} 字符)")

    def _inject_hidden_ctx(self, event: AstrMessageEvent, req: ProviderRequest):
        """⚠️ [实验性功能] 每次 LLM 请求前，将缓冲区的原文注入 req.contexts 作为伪造 assistant 消息。
        仅当 enable_hidden_ctx_buffer=True 时生效。
        """
        if not self.config.get("enable_hidden_ctx_buffer", True):
            return
        chat_id = self._get_user_id(event)
        buf = self._hidden_ctx_buffer.get(chat_id)
        if not buf:
            return
        if not hasattr(req, "contexts") or req.contexts is None:
            return
        inject_count = 0
        for entry in buf:
            req.contexts.append({
                "role": "assistant",
                "content": f"[已渲染成图片发送的原始内容]\n{entry['content']}",
            })
            inject_count += 1
        if inject_count > 0:
            logger.info(f"[实验性][Hidden] 注入 {inject_count} 条隐藏上下文到 LLM 请求")

    # ==================== 事件钩子 ====================

    @filter.on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, req: ProviderRequest):
        inject_template_prompts = self.config.get("inject_template_prompts", False)
        if inject_template_prompts:
            available_templates = self._get_available_templates()
            if available_templates:
                all_prompts = self.template_mgr.extract_all_builtin_prompts()
                if all_prompts:
                    user_id = self._get_user_id(event)
                    current_template = self._get_default_template(user_id)

                    prompt_sections = []
                    prompt_sections.append("## 模板专属指令")
                    prompt_sections.append(f"当前用户偏好的模板是: **{current_template}**")
                    prompt_sections.append("")

                    for tpl_name, tpl_prompt in all_prompts.items():
                        is_current = " （当前用户偏好）" if tpl_name == current_template else ""
                        prompt_sections.append(f"### 模板「{tpl_name}」的专属指令{is_current}")
                        prompt_sections.append(tpl_prompt)
                        prompt_sections.append("")

                    builtin_block = "\n".join(prompt_sections)
                    req.system_prompt += f"\n\n{builtin_block}"
                    logger.info(f"[HTML渲染] 已注入 {len(all_prompts)} 个模板的内置提示词，当前偏好: {current_template}")

        # 注入隐藏上下文缓冲（原文仅 LLM 可见，不在消息链中）
        self._inject_hidden_ctx(event, req)
