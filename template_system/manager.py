import json
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

from astrbot.api import logger


class TemplateManager:
    """Manage read-only built-in templates and persistent custom templates."""

    CUSTOM_STARTER_NAME = "custom"
    CUSTOM_STARTER_FILE = "custom.default.html"
    CUSTOM_STARTER_DISPLAY_NAME = "Custom 起始页"
    CUSTOM_STARTER_DESCRIPTION = (
        "自由编辑的 HTML/CSS 起始模板，不绑定排版滑条，可任意改版。"
    )
    CUSTOM_STARTER_TAGS = ["自由改版", "HTML/CSS", "实时预览"]
    _BUILTIN_PROMPT_PATTERN = re.compile(
        r"<!--\s*BUILTIN_PROMPT\s*?\n(.*?)-->",
        re.DOTALL,
    )
    _SAFE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
    _UNSAFE_TEMPLATE_PATTERNS = (
        (
            re.compile(r"<\s*(?:script|iframe|object|embed|base)\b", re.I),
            "不允许脚本或嵌入页面",
        ),
        (re.compile(r"<\s*meta\b[^>]*http-equiv", re.I), "不允许页面跳转元数据"),
        (re.compile(r"\bon[a-z]+\s*=", re.I), "不允许事件属性"),
        (re.compile(r"(?:javascript|vbscript)\s*:", re.I), "不允许脚本 URL"),
        (re.compile(r"(?:https?|file)\s*:", re.I), "不允许远程或本机文件 URL"),
        (
            re.compile(
                r"(?:src|href)\s*=\s*[\"']?\s*//|url\(\s*[\"']?\s*//",
                re.I,
            ),
            "不允许省略协议的远程 URL",
        ),
        (re.compile(r"@import\b", re.I), "不允许 CSS @import"),
    )
    MAX_TEMPLATE_BYTES = 256 * 1024

    def __init__(self, template_dir: str, custom_template_dir: str | None = None):
        self.TEMPLATE_DIR = template_dir
        self.CUSTOM_TEMPLATE_DIR = custom_template_dir
        self.templates: Dict[str, str] = {}
        self.template_id_map: Dict[int, str] = {}
        self.manifest: Dict[str, Dict[str, Any]] = {}
        self.custom_manifest: Dict[str, Dict[str, Any]] = {}
        self.load_manifest()

    def load_manifest(self) -> None:
        """Load optional presentation and paper metadata for templates."""

        self.manifest = {}
        self.custom_manifest = {}
        self.manifest = self._read_manifest(
            os.path.join(self.TEMPLATE_DIR, "manifest.json"),
            "内置模板",
        )
        if self.CUSTOM_TEMPLATE_DIR:
            self.custom_manifest = self._read_manifest(
                os.path.join(self.CUSTOM_TEMPLATE_DIR, "manifest.json"),
                "自定义模板",
            )

    @staticmethod
    def _read_manifest(path: str, label: str) -> Dict[str, Dict[str, Any]]:
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            templates = raw.get("templates", raw)
            if isinstance(templates, dict):
                return {
                    str(name): meta
                    for name, meta in templates.items()
                    if isinstance(meta, dict)
                }
        except Exception as exc:
            logger.warning(f"[HTML渲染] {label} manifest 读取失败: {exc}")
        return {}

    async def load_templates(self):
        """Preload templates from disk for startup diagnostics."""
        self.templates = {}
        self.load_manifest()
        os.makedirs(self.TEMPLATE_DIR, exist_ok=True)
        if self.CUSTOM_TEMPLATE_DIR:
            os.makedirs(self.CUSTOM_TEMPLATE_DIR, exist_ok=True)

        for template_name in self.get_available_templates():
            filepath = self._template_path(template_name)
            try:
                with open(filepath, "r", encoding="utf-8") as handle:
                    self.templates[template_name] = handle.read()
                logger.info(f"[HTML渲染] 已加载模板: {template_name}")
            except Exception as exc:
                logger.error(f"[HTML渲染] 加载模板 {filepath} 失败: {exc}")

        if not self.templates:
            logger.warning(
                f"[HTML渲染] 未找到任何模板文件，请先在 {self.TEMPLATE_DIR} 中放入至少一个 .html 模板"
            )

    def get_available_templates(self) -> List[str]:
        """Return readable HTML templates containing the content placeholder.

        Built-in templates follow manifest order, then custom templates alphabetically,
        so the default template stays stable as new built-ins are added.
        """
        templates = set()
        for directory in self._template_directories():
            if not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                if not filename.endswith(".html"):
                    continue
                filepath = os.path.join(directory, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as handle:
                        if "{{content}}" in handle.read():
                            templates.add(filename[:-5])
                        else:
                            logger.warning(
                                f"[HTML渲染] 已忽略缺少 {{{{content}}}} 占位符的模板: {filepath}"
                            )
                except Exception as exc:
                    logger.warning(f"[HTML渲染] 已忽略无法读取的模板 {filepath}: {exc}")
        builtin = {
            name
            for name in templates
            if os.path.isfile(os.path.join(self.TEMPLATE_DIR, f"{name}.html"))
        }
        manifest_index = {name: index for index, name in enumerate(self.manifest)}
        builtin_sorted = sorted(
            builtin,
            key=lambda name: (manifest_index.get(name, len(self.manifest)), name),
        )
        custom_sorted = sorted(templates - builtin)
        return builtin_sorted + custom_sorted

    def get_builtin_templates(self) -> List[str]:
        return self._available_in_directory(self.TEMPLATE_DIR)

    def get_custom_templates(self) -> List[str]:
        if not self.CUSTOM_TEMPLATE_DIR:
            return []
        builtins = set(self.get_builtin_templates())
        return [
            name
            for name in self._available_in_directory(self.CUSTOM_TEMPLATE_DIR)
            if name not in builtins
        ]

    @staticmethod
    def _available_in_directory(directory: str) -> List[str]:
        if not os.path.isdir(directory):
            return []
        result: list[str] = []
        for filename in os.listdir(directory):
            if not filename.endswith(".html"):
                continue
            path = os.path.join(directory, filename)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    if "{{content}}" in handle.read():
                        result.append(filename[:-5])
            except OSError:
                continue
        return sorted(set(result))

    def _template_directories(self) -> list[str]:
        directories = [self.TEMPLATE_DIR]
        if self.CUSTOM_TEMPLATE_DIR:
            directories.append(self.CUSTOM_TEMPLATE_DIR)
        return directories

    def _template_path(self, template_name: str) -> str:
        if template_name in self.get_custom_templates() and self.CUSTOM_TEMPLATE_DIR:
            return os.path.join(self.CUSTOM_TEMPLATE_DIR, f"{template_name}.html")
        return os.path.join(self.TEMPLATE_DIR, f"{template_name}.html")

    def require_available_templates(self) -> List[str]:
        templates = self.get_available_templates()
        if templates:
            return templates

        raise FileNotFoundError(
            f"未找到任何模板文件，请先在 {self.TEMPLATE_DIR} 中放入至少一个 .html 模板"
        )

    def has_template(self, template_name: Optional[str]) -> bool:
        if not template_name:
            return False
        return template_name in self.get_available_templates()

    def load_template(self, template_name: str) -> str:
        """Load one template from disk on demand."""
        if not template_name:
            raise ValueError("模板名不能为空")

        filepath = self._template_path(template_name)
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"模板不存在: {template_name} ({filepath})")

        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception as exc:
            raise RuntimeError(f"读取模板失败: {template_name}: {exc}") from exc

        if "{{content}}" not in content:
            raise ValueError(f"模板缺少 {{{{content}}}} 占位符: {template_name}")

        return self.strip_builtin_prompt(content)

    @classmethod
    def strip_builtin_prompt(cls, html: str) -> str:
        """Remove BUILTIN_PROMPT comment blocks before rendering."""
        return cls._BUILTIN_PROMPT_PATTERN.sub("", html)

    def extract_builtin_prompt(self, template_name: str) -> Optional[str]:
        filepath = self._template_path(template_name)
        if not os.path.isfile(filepath):
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                raw_html = handle.read()
        except Exception as exc:
            logger.error(f"[HTML渲染] 读取模板 {template_name} 失败: {exc}")
            return None

        match = self._BUILTIN_PROMPT_PATTERN.search(raw_html)
        if not match:
            return None

        prompt = match.group(1).strip()
        return prompt or None

    def extract_all_builtin_prompts(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for template_name in self.get_available_templates():
            prompt = self.extract_builtin_prompt(template_name)
            if prompt:
                result[template_name] = prompt
        return result

    def get_template_metadata(self, template_name: str) -> Dict[str, Any]:
        custom = self.custom_manifest.get(template_name, {})
        if isinstance(custom, dict) and custom:
            base_name = str(custom.get("base_template", "") or "")
            base = self.manifest.get(base_name, {})
            metadata = dict(base) if isinstance(base, dict) else {}
            metadata.update(custom)
            metadata["source"] = "custom"
            metadata["editable"] = True
            return metadata
        metadata = self.manifest.get(template_name, {})
        result = dict(metadata) if isinstance(metadata, dict) else {}
        result["source"] = "builtin"
        result["editable"] = False
        return result

    def get_all_template_metadata(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: self.get_template_metadata(name)
            for name in self.get_available_templates()
        }

    def update_template_id_map(self):
        available = self.get_available_templates()
        self.template_id_map = {
            idx: name for idx, name in enumerate(available, start=1)
        }
        logger.debug(f"[HTML渲染] 模板 ID 映射已更新: {self.template_id_map}")

    @classmethod
    def validate_template_name(cls, name: str) -> str:
        normalized = str(name or "").strip().lower()
        if not cls._SAFE_NAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "模板名须以小写字母开头，只能包含小写字母、数字、下划线或连字符，最长 48 位"
            )
        return normalized

    @classmethod
    def validate_custom_html(cls, html: str) -> str:
        content = str(html or "")
        if not content.strip():
            raise ValueError("模板 HTML 不能为空")
        if len(content.encode("utf-8")) > cls.MAX_TEMPLATE_BYTES:
            raise ValueError("模板 HTML 超过 256 KiB 上限")
        if "{{content}}" not in content:
            raise ValueError("模板必须包含 {{content}} 占位符")
        for pattern, message in cls._UNSAFE_TEMPLATE_PATTERNS:
            if pattern.search(content):
                raise ValueError(message)
        return content

    def save_custom_template(
        self,
        name: str,
        html: str,
        *,
        display_name: str = "",
        description: str = "",
        base_template: str = "classic",
    ) -> Dict[str, Any]:
        if not self.CUSTOM_TEMPLATE_DIR:
            raise RuntimeError("未配置自定义模板目录")
        normalized = self.validate_template_name(name)
        if normalized in self.get_builtin_templates():
            raise ValueError("内置模板为只读，请换一个模板名")
        content = self.validate_custom_html(html)
        if base_template not in self.get_builtin_templates():
            base_template = (
                "classic" if "classic" in self.get_builtin_templates() else ""
            )

        os.makedirs(self.CUSTOM_TEMPLATE_DIR, exist_ok=True)
        template_path = os.path.join(self.CUSTOM_TEMPLATE_DIR, f"{normalized}.html")
        self._atomic_write_text(template_path, content)
        metadata = {
            "display_name": str(display_name or normalized).strip()[:80],
            "description": str(description or "自定义模板").strip()[:240],
            "scene": "custom",
            "thumbnail": "dynamic",
            "tags": (
                list(self.CUSTOM_STARTER_TAGS)
                if normalized == self.CUSTOM_STARTER_NAME
                else ["自定义", "HTML/CSS", "可编辑"]
            ),
            "base_template": base_template,
        }
        if normalized == self.CUSTOM_STARTER_NAME:
            metadata["css_variables"] = []
        self.custom_manifest[normalized] = metadata
        self._save_custom_manifest()
        self.templates[normalized] = content
        self.update_template_id_map()
        return self.get_template_metadata(normalized)

    def ensure_custom_slot(
        self,
        name: str = "custom",
        *,
        base_template: str = "classic",
    ) -> Dict[str, Any]:
        """Create or safely upgrade the single editable WebUI template."""

        normalized = self.validate_template_name(name)
        builtins = self.get_builtin_templates()
        if not builtins:
            raise FileNotFoundError("没有可用于初始化 Custom 的内置模板")
        base = base_template if base_template in builtins else builtins[0]
        starter = self._load_custom_starter()
        if normalized in self.get_custom_templates():
            if starter:
                current_html = self.load_template(normalized)
                metadata = self.get_template_metadata(normalized)
                is_legacy_clone = current_html == self.load_template(base)
                starter_metadata_is_stale = current_html == starter and (
                    metadata.get("display_name") != self.CUSTOM_STARTER_DISPLAY_NAME
                    or metadata.get("description") != self.CUSTOM_STARTER_DESCRIPTION
                    or metadata.get("tags") != self.CUSTOM_STARTER_TAGS
                )
                if is_legacy_clone or starter_metadata_is_stale:
                    return self.save_custom_template(
                        normalized,
                        starter,
                        display_name=self.CUSTOM_STARTER_DISPLAY_NAME,
                        description=self.CUSTOM_STARTER_DESCRIPTION,
                        base_template=base,
                    )
            return self.get_template_metadata(normalized)
        return self.save_custom_template(
            normalized,
            starter or self.load_template(base),
            display_name=self.CUSTOM_STARTER_DISPLAY_NAME,
            description=self.CUSTOM_STARTER_DESCRIPTION,
            base_template=base,
        )

    def _load_custom_starter(self) -> str:
        starter_path = os.path.join(
            self.TEMPLATE_DIR,
            "_starters",
            self.CUSTOM_STARTER_FILE,
        )
        if not os.path.isfile(starter_path):
            return ""
        try:
            with open(starter_path, "r", encoding="utf-8") as handle:
                return self.validate_custom_html(handle.read())
        except (OSError, ValueError) as exc:
            logger.warning(f"[HTML渲染] Custom 默认模板读取失败: {exc}")
            return ""

    def delete_custom_template(self, name: str) -> None:
        if not self.CUSTOM_TEMPLATE_DIR:
            raise RuntimeError("未配置自定义模板目录")
        normalized = self.validate_template_name(name)
        if normalized not in self.get_custom_templates():
            raise ValueError("只能删除已存在的自定义模板")
        path = os.path.abspath(
            os.path.join(self.CUSTOM_TEMPLATE_DIR, f"{normalized}.html")
        )
        custom_root = os.path.abspath(self.CUSTOM_TEMPLATE_DIR)
        if os.path.commonpath([path, custom_root]) != custom_root:
            raise ValueError("模板路径越界")
        os.remove(path)
        self.custom_manifest.pop(normalized, None)
        self.templates.pop(normalized, None)
        self._save_custom_manifest()
        self.update_template_id_map()

    def duplicate_template(
        self,
        source: str,
        target: str,
        *,
        display_name: str = "",
    ) -> Dict[str, Any]:
        if not self.has_template(source):
            raise ValueError("源模板不存在")
        metadata = self.get_template_metadata(source)
        base = (
            source
            if source in self.get_builtin_templates()
            else str(metadata.get("base_template", "classic"))
        )
        return self.save_custom_template(
            target,
            self.load_template(source),
            display_name=display_name or f"{metadata.get('display_name', source)} 副本",
            description=f"复制自 {source}",
            base_template=base,
        )

    def _save_custom_manifest(self) -> None:
        if not self.CUSTOM_TEMPLATE_DIR:
            return
        path = os.path.join(self.CUSTOM_TEMPLATE_DIR, "manifest.json")
        payload = {
            "schema_version": 1,
            "templates": self.custom_manifest,
        }
        self._atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    @staticmethod
    def _atomic_write_text(path: str, content: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=directory,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def get_default_test_content(template_name: Optional[str] = None) -> str:
        _ = template_name
        return """# HTML Render Preview

这是一段模板预览文本。
这里会测试普通段落、列表、代码块和数学公式。

- 项目一
- 项目二

```python
print("Hello from AstrBot")
```

行内公式 $a^2 + b^2 = c^2$

$$
\\int_0^1 x^2 dx = \\frac{1}{3}
$$
"""

    @staticmethod
    def get_gif_test_content() -> str:
        return """<render gif>
<style>
body {
    margin: 0;
    padding: 24px;
    background: linear-gradient(135deg, #0f172a, #1e293b);
    font-family: "Microsoft YaHei", sans-serif;
}
.stage {
    width: 520px;
    padding: 28px;
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.12);
    color: #f8fafc;
    overflow: hidden;
    box-shadow: 0 16px 48px rgba(15, 23, 42, 0.28);
}
.track {
    display: inline-block;
    white-space: nowrap;
    font-size: 32px;
    font-weight: 700;
    letter-spacing: 2px;
    animation: slide 4s linear infinite;
}
@keyframes slide {
    0% { transform: translateX(100%); }
    100% { transform: translateX(-120%); }
}
</style>
<div class="stage">
    <div class="track">AstrBot HTML Render GIF Preview</div>
</div>
</render>"""
