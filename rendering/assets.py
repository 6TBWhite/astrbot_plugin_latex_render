"""Local HTML assets used by browser-ready rendering documents."""

from __future__ import annotations

import base64
import json
import os
import random
import re

from PIL import Image as PILImage
from astrbot.api import logger

from ..config import RenderConfig
from ..template_system.service import TemplateService


CODE_THEME_BY_SCENE = {
    "knowledge": "github-dark",
    "story": "docco",
    "inspiration": "night-owl",
    "paper": "github",
    "custom": "night-owl",
}
CODE_LANGUAGE_ALIASES = {
    "c++": "cpp",
    "c#": "csharp",
    "cs": "csharp",
    "html": "xml",
    "htm": "xml",
    "js": "javascript",
    "md": "markdown",
    "py": "python",
    "sh": "bash",
    "ts": "typescript",
    "txt": "plaintext",
    "text": "plaintext",
    "yml": "yaml",
    "zsh": "bash",
}
CODE_LANGUAGE_LABELS = {
    "bash": "Bash",
    "c": "C",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "cs": "C#",
    "csharp": "C#",
    "html": "HTML",
    "htm": "HTML",
    "xml": "XML",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "json": "JSON",
    "py": "Python",
    "python": "Python",
    "sh": "Bash",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "txt": "Text",
    "text": "Text",
    "plaintext": "Text",
    "yml": "YAML",
    "yaml": "YAML",
    "zsh": "Bash",
}

CODE_HIGHLIGHT_LOADER = """
<script data-astrbot-code-highlight-loader>
window.__ASTR_CODE_HIGHLIGHT_READY__ = false;
(function () {
  const aliases = __ASTR_CODE_ALIASES__;
  const labels = __ASTR_CODE_LABELS__;
  const languageClass = /^language-([a-z0-9][a-z0-9_+#-]{0,31})$/i;
  function finish() { window.__ASTR_CODE_HIGHLIGHT_READY__ = true; }
  function highlightCode() {
    try {
      const script = document.createElement('script');
      script.id = 'astrbot-highlight-script';
      script.textContent = atob(__ASTR_HIGHLIGHT_SOURCE__);
      document.head.appendChild(script);
      if (!window.hljs || typeof window.hljs.highlightElement !== 'function') return;
      document.querySelectorAll('pre > code').forEach(function (block) {
        const sourceClass = Array.from(block.classList).find(function (name) { return languageClass.test(name); });
        if (!sourceClass) return;
        const rawLanguage = sourceClass.slice('language-'.length).toLowerCase();
        const language = aliases[rawLanguage] || rawLanguage;
        const canonicalClass = 'language-' + language;
        if (canonicalClass !== sourceClass) {
          block.classList.remove(sourceClass);
          block.classList.add(canonicalClass);
        }
        const pre = block.parentElement;
        if (pre && !pre.querySelector(':scope > .astr-code-language')) {
          const label = document.createElement('span');
          label.className = 'astr-code-language';
          label.textContent = labels[rawLanguage] || labels[language] || rawLanguage.toUpperCase();
          pre.insertBefore(label, block);
        }
        if (typeof window.hljs.getLanguage === 'function' && window.hljs.getLanguage(language)) {
          window.hljs.highlightElement(block);
        }
      });
    } catch (error) {
      console.warn('AstrBot code highlighting failed', error);
    } finally { finish(); }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', highlightCode, {once: true});
  } else { highlightCode(); }
})();
</script>
"""


def build_code_highlight_assets(
    encoded_script: str, theme_name: str, theme_source: str
) -> str:
    loader = (
        CODE_HIGHLIGHT_LOADER.replace(
            "__ASTR_CODE_ALIASES__",
            json.dumps(CODE_LANGUAGE_ALIASES, ensure_ascii=True),
        )
        .replace(
            "__ASTR_CODE_LABELS__", json.dumps(CODE_LANGUAGE_LABELS, ensure_ascii=True)
        )
        .replace("__ASTR_HIGHLIGHT_SOURCE__", repr(encoded_script))
    )
    return f"""
<style id="astrbot-code-highlight-theme" data-theme="{theme_name}">
{theme_source}
pre > code.hljs {{ display: block; padding: 0; overflow: visible; color: inherit; background: transparent; }}
pre > .astr-code-language {{
  display: block; margin: 0 0 0.65em; color: inherit;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 0.72em; font-weight: 600; line-height: 1; letter-spacing: 0.08em;
  text-align: right; text-transform: uppercase; white-space: normal; opacity: 0.68;
  user-select: none;
}}
</style>
{loader}
"""


class HtmlAssets:
    def __init__(
        self, config: RenderConfig, templates: TemplateService, plugin_dir: str
    ):
        self.config = config
        self.templates = templates
        self.plugin_dir = plugin_dir
        self.background_cache: dict[str, tuple[str, tuple[int, int]]] = {}
        self.code_cache: dict[str, tuple[str, str] | None] = {}
        self.background_size: tuple[int, int] | None = None
        self.background_index = 0
        self.mathjax_source: str | None = None

    def _background_strategy(self) -> str:
        strategy = (
            str(self.config.get("background_image_strategy", "fixed") or "fixed")
            .strip()
            .lower()
        )
        return strategy if strategy in {"fixed", "round_robin", "random"} else "fixed"

    def _select_background(self) -> str:
        configured = str(self.config.get("background_image", "") or "").strip()
        strategy = self._background_strategy()
        available = self.templates.background_images()
        if strategy == "fixed":
            return configured
        if not available:
            return ""
        if strategy == "random":
            return random.choice(available)
        selected = available[self.background_index % len(available)]
        self.background_index += 1
        return selected

    def background_data_url(self) -> str:
        configured = self._select_background()
        if not configured:
            self.background_size = None
            return ""
        if configured not in set(self.templates.background_images()):
            logger.warning(f"[HTML渲染] 背景图片不在管理员素材目录中: {configured}")
            self.background_size = None
            return ""
        cached = self.background_cache.get(configured)
        if cached:
            self.background_size = cached[1]
            return cached[0]
        path = os.path.join(self.plugin_dir, configured.replace("/", os.sep))
        try:
            mime = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(os.path.splitext(path)[1].lower(), "image/png")
            with PILImage.open(path) as image:
                size = (max(1, image.width), max(1, image.height))
            with open(path, "rb") as handle:
                data_url = f"data:{mime};base64,{base64.b64encode(handle.read()).decode('utf-8')}"
            self.background_cache[configured] = (data_url, size)
            self.background_size = size
            logger.info(f"[HTML渲染] 背景图片已加载: {configured} ({mime})")
            return data_url
        except Exception as exc:
            logger.warning(f"[HTML渲染] 读取背景图片失败: {exc}")
            self.background_size = None
            return ""

    def inject_math(self, html_content: str) -> str:
        if (
            'id="astrbot-mathjax-script"' in html_content
            or "data-astrbot-mathjax-loader" in html_content
        ):
            return html_content
        if self.mathjax_source is None:
            path = os.path.join(self.plugin_dir, "assets", "mathjax-tex-svg.js")
            try:
                self.mathjax_source = (
                    open(path, encoding="utf-8").read() if os.path.exists(path) else ""
                )
            except OSError as exc:
                logger.warning(f"[HTML 渲染] 读取本地 MathJax 失败: {exc}")
                self.mathjax_source = ""
        if self.mathjax_source:
            encoded = base64.b64encode(self.mathjax_source.encode("utf-8")).decode(
                "ascii"
            )
            loader = f"""<script data-astrbot-mathjax-loader>(function(){{var code=atob({encoded!r});var s=document.createElement('script');s.id='astrbot-mathjax-script';s.type='text/javascript';s.textContent=code;s.onerror=function(){{window.__ASTR_SET_MATH_STATUS__('failed','MathJax script load failed');}};if(document.readyState==='loading'){{document.addEventListener('DOMContentLoaded',function(){{document.head.appendChild(s);}});}}else{{document.head.appendChild(s);}}}})();</script>"""
        else:
            loader = '<script id="astrbot-mathjax-script" data-astrbot-mathjax-loader defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js" onerror="window.__ASTR_SET_MATH_STATUS__(\'failed\',\'MathJax script load failed\');"></script>'
        assets = (
            """
<style>
.astr-math-inline,.astr-math-block{max-width:100%;}.astr-math-block{display:block;margin:.9em 0;overflow-x:auto;overflow-y:hidden;text-align:center;}
mjx-container,mjx-container *{word-break:normal!important;overflow-wrap:normal!important;}mjx-container[jax="SVG"]{max-width:100%;}
.astr-math-block mjx-container[jax="SVG"]{display:inline-block!important;margin:0 auto!important;}
</style>
<script>
window.__ASTR_MATH_STATUS__={state:'pending',error:''};
window.__ASTR_SET_MATH_STATUS__=(state,error='')=>{window.__ASTR_MATH_STATUS__={state,error:String(error||'')}};
window.MathJax={tex:{inlineMath:[['$','$'],['\\\\(','\\\\)']],displayMath:[['$$','$$'],['\\\\[','\\\\]']],processEscapes:true,processEnvironments:true,packages:{'[+]':['ams'],'[-]':['noundefined']}},svg:{fontCache:'global'},options:{skipHtmlTags:['script','noscript','style','textarea','pre','code']},startup:{pageReady:()=>MathJax.startup.defaultPageReady().then(()=>{window.__ASTR_SET_MATH_STATUS__('ready');}).catch(error=>{window.__ASTR_SET_MATH_STATUS__('failed',error&&error.message?error.message:error);})}};
</script>
"""
            + loader
        )
        return (
            html_content.replace("</head>", assets + "</head>", 1)
            if "</head>" in html_content
            else assets + html_content
        )

    def load_code_highlight(self, theme_name: str) -> tuple[str, str] | None:
        if theme_name in self.code_cache:
            return self.code_cache[theme_name]
        directory = os.path.join(self.plugin_dir, "assets", "highlight")
        try:
            script = open(
                os.path.join(directory, "highlight.min.js"), encoding="utf-8"
            ).read()
            theme = open(
                os.path.join(directory, "styles", f"{theme_name}.css"), encoding="utf-8"
            ).read()
        except OSError as exc:
            logger.warning(f"[HTML渲染] 读取本地代码高亮资源失败: {exc}")
            self.code_cache[theme_name] = None
            return None
        encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
        self.code_cache[theme_name] = (encoded, theme)
        logger.info(f"[HTML渲染] 已加载本地 Highlight.js 11.11.2: {theme_name}")
        return self.code_cache[theme_name]

    def inject_code_highlight(self, html_content: str, scene: str) -> str:
        if not self.config.boolean("enable_code_highlight", True):
            return html_content
        if "data-astrbot-code-highlight-loader" in html_content or not re.search(
            r'<pre\b[^>]*>\s*<code\b[^>]*class=["\'][^"\']*\blanguage-',
            html_content,
            re.IGNORECASE,
        ):
            return html_content
        theme_name = CODE_THEME_BY_SCENE.get(str(scene), "github")
        assets = self.load_code_highlight(theme_name)
        if not assets:
            return html_content
        block = build_code_highlight_assets(assets[0], theme_name, assets[1])
        return (
            html_content.replace("</head>", block + "</head>", 1)
            if "</head>" in html_content
            else block + html_content
        )

    def _background_mode(self) -> str:
        mode = (
            str(self.config.get("background_render_mode", "ambient") or "ambient")
            .strip()
            .lower()
        )
        return mode if mode in {"ambient", "watermark"} else "ambient"

    def inject_background(self, html_content: str, data_url: str) -> str:
        if not data_url or 'id="astrbot-custom-bg-style"' in html_content:
            return html_content
        mode = self._background_mode()
        default_opacity = 0.17 if mode == "watermark" else 0.22
        opacity = self.config.number("background_opacity", default_opacity, 0.0, 1.0)
        size = self.background_size
        ratio = (
            f"{size[0]} / {size[1]}"
            if size and size[0] > 0 and size[1] > 0
            else "1 / 1"
        )
        if mode == "watermark":
            css = f"""<style id="astrbot-custom-bg-style">html{{background:transparent!important}}body{{position:relative!important;background:transparent!important}}.content{{position:relative!important;isolation:isolate!important;z-index:0}}.content::before{{content:"";position:absolute;top:18px;left:50%;width:calc(100% + 20px);max-width:calc(100% + 20px);aspect-ratio:{ratio};height:auto;transform:translateX(-50%) scale(1.015);transform-origin:center top;z-index:0;pointer-events:none;background-image:url("{data_url}");background-size:100% auto;background-position:center top;background-repeat:no-repeat;opacity:{opacity};filter:saturate(.92) contrast(.97);mix-blend-mode:multiply}}.content>*{{position:relative;z-index:1}}</style>"""
        else:
            css = f"""<style id="astrbot-custom-bg-style">html{{background:transparent!important}}body{{position:relative!important;isolation:isolate!important;background:transparent!important}}body::before{{content:"";position:absolute;inset:0;z-index:-2;pointer-events:none;background-image:url("{data_url}");background-size:102% auto;background-position:center top;background-repeat:repeat-y;background-attachment:scroll;opacity:{opacity};filter:blur(6px) saturate(.95);transform:scale(1.015);transform-origin:center top}}body::after{{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;background:linear-gradient(180deg,rgba(255,255,255,.20),rgba(255,255,255,.12)),radial-gradient(circle at top,rgba(255,255,255,.16),rgba(255,255,255,.03) 55%)}}body>*{{position:relative;z-index:1}}</style>"""
        return (
            html_content.replace("</head>", css + "</head>", 1)
            if "</head>" in html_content
            else css + html_content
        )
