"""AstrBot WebUI backend controller for the rendering studio."""

from __future__ import annotations

import base64
import os

from astrbot.api import logger

try:
    from astrbot.api.web import json_response, request
except ImportError:

    def json_response(payload):
        return payload

    request = None

from ..config import (
    STYLE_CONTROL_SPECS,
    WEB_CONFIG_SPECS,
    normalize_layout,
)
from ..rendering.models import RenderFailure
from ..template_system.manager import TemplateManager
from .actions import RenderActions


class WebUIController:
    ROUTES = (
        ("bootstrap", "bootstrap", ["GET"], "读取渲染工作台数据"),
        ("config", "save_config", ["POST"], "保存渲染工作台配置"),
        ("config/reset", "reset_config", ["POST"], "重置渲染工作台配置"),
        ("preview", "preview", ["POST"], "生成模板实时预览"),
        ("template", "template", ["GET"], "读取模板源码"),
        ("template/save", "save_template", ["POST"], "保存自定义模板"),
        ("template/delete", "delete_template", ["POST"], "删除自定义模板"),
        (
            "template/duplicate",
            "duplicate_template",
            ["POST"],
            "复制模板为自定义模板",
        ),
        ("templates/export", "export_templates", ["GET"], "导出自定义模板"),
        ("templates/import", "import_templates", ["POST"], "导入自定义模板"),
        ("status", "status", ["GET"], "读取渲染器诊断状态"),
    )

    def __init__(
        self,
        context,
        actions: RenderActions,
        plugin_name: str,
        version: str,
    ):
        self.context = context
        self.actions = actions
        self.config = actions.config
        self.preferences = actions.preferences
        self.templates = actions.templates
        self.pipeline = actions.pipeline
        self.diagnostics = actions.diagnostics
        self.plugin_name = plugin_name
        self.version = version

    def register(self) -> None:
        if not hasattr(self.context, "register_web_api"):
            return
        prefix = f"/{self.plugin_name}/page"
        for suffix, handler_name, methods, description in self.ROUTES:
            self.context.register_web_api(
                f"{prefix}/{suffix}",
                getattr(self, handler_name),
                methods,
                description,
            )

    @staticmethod
    async def request_body() -> dict:
        if request is None:
            return {}
        try:
            result = await request.json({})
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def query_value(name: str) -> str:
        if request is None:
            return ""
        try:
            return str(request.query.get(name, "") or "").strip()
        except Exception:
            return ""

    def template_payload(self) -> list[dict]:
        payload = []
        for name in self.templates.available():
            metadata = self.templates.manager.get_template_metadata(name)
            controls = []
            for key in metadata.get("css_variables", []):
                spec = STYLE_CONTROL_SPECS.get(str(key))
                if spec:
                    controls.append(
                        {
                            "key": key,
                            **spec,
                            "value": self.config.get(key, spec["default"]),
                        }
                    )
            payload.append(
                {
                    "name": name,
                    "display_name": metadata.get("display_name", name),
                    "description": metadata.get("description", ""),
                    "scene": metadata.get("scene", "custom"),
                    "tags": metadata.get("tags", []),
                    "source": metadata.get("source", "builtin"),
                    "editable": bool(metadata.get("editable", False)),
                    "base_template": metadata.get("base_template", name),
                    "controls": controls,
                    "fixed_page": metadata.get("fixed_page"),
                }
            )
        return payload

    async def bootstrap(self):
        return json_response(
            {
                "ok": True,
                "plugin": {
                    "id": self.plugin_name,
                    "display_name": "LaTeX / Markdown 图片渲染",
                    "version": self.version,
                },
                "config_fields": self.config.web_payload(self.templates.available()),
                "templates": self.template_payload(),
                "preview_content": TemplateManager.get_default_test_content(),
                "status": self.diagnostics.safe_status(),
            }
        )

    async def save_config(self):
        body = await self.request_body()
        values = body.get("values")
        if not isinstance(values, dict):
            return json_response({"error": "invalid_request_body"})
        try:
            template_name = str(body.get("template", "") or "").strip()
            if template_name:
                if not self.templates.has(template_name):
                    raise ValueError("模板不存在")
                metadata = self.templates.manager.get_template_metadata(template_name)
                allowed = {str(key) for key in metadata.get("css_variables", [])}
                normalized = self.config.normalize_style_values(values, allowed)
            else:
                normalized = self.config.normalize_web_values(
                    values, self.templates.available()
                )
            if not normalized:
                raise ValueError("没有可保存的配置项")
            self._save_runtime_config(normalized)
            return json_response(
                {
                    "ok": True,
                    "saved": normalized,
                    "config_fields": self.config.web_payload(
                        self.templates.available()
                    ),
                    "templates": self.template_payload(),
                }
            )
        except ValueError as exc:
            return json_response({"error": "invalid_config", "message": str(exc)})
        except Exception as exc:
            logger.exception(f"[HTML渲染] WebUI 保存配置失败: {exc}")
            return json_response({"error": "save_failed", "message": "配置保存失败"})

    async def reset_config(self):
        body = await self.request_body()
        template_name = str(body.get("template", "") or "").strip()
        if template_name:
            if not self.templates.has(template_name):
                return json_response(
                    {"error": "invalid_template", "message": "模板不存在"}
                )
            metadata = self.templates.manager.get_template_metadata(template_name)
            values = {
                key: STYLE_CONTROL_SPECS[key]["default"]
                for key in metadata.get("css_variables", [])
                if key in STYLE_CONTROL_SPECS
            }
        else:
            values = {key: spec["default"] for key, spec in WEB_CONFIG_SPECS.items()}
        self._save_runtime_config(values)
        return json_response(
            {
                "ok": True,
                "saved": values,
                "config_fields": self.config.web_payload(self.templates.available()),
                "templates": self.template_payload(),
            }
        )

    def _save_runtime_config(self, values: dict) -> None:
        self.config.save(values)
        self.templates.refresh_schema_options()

    async def template(self):
        name = self.query_value("name")
        if not self.templates.has(name):
            return json_response({"error": "invalid_template", "message": "模板不存在"})
        try:
            html = self.templates.manager.load_template(name)
        except Exception as exc:
            return json_response({"error": "template_read_failed", "message": str(exc)})
        return json_response(
            {
                "ok": True,
                "name": name,
                "html": html,
                "metadata": self.templates.manager.get_template_metadata(name),
            }
        )

    async def save_template(self):
        body = await self.request_body()
        try:
            metadata = self.templates.manager.save_custom_template(
                str(body.get("name", "") or ""),
                str(body.get("html", "") or ""),
                display_name=str(body.get("display_name", "") or ""),
                description=str(body.get("description", "") or ""),
                base_template=str(body.get("base_template", "classic") or "classic"),
            )
            self.templates.refresh_schema_options()
            return json_response(
                {
                    "ok": True,
                    "metadata": metadata,
                    "templates": self.template_payload(),
                }
            )
        except ValueError as exc:
            return json_response({"error": "invalid_template", "message": str(exc)})
        except Exception as exc:
            logger.exception(f"[HTML渲染] WebUI 保存自定义模板失败: {exc}")
            return json_response(
                {"error": "save_failed", "message": "自定义模板保存失败"}
            )

    async def delete_template(self):
        body = await self.request_body()
        name = str(body.get("name", "") or "").strip()
        try:
            self.templates.manager.delete_custom_template(name)
            cleared = self.clear_removed_template_references(name)
            self.templates.refresh_schema_options()
            return json_response(
                {
                    "ok": True,
                    "name": name,
                    "preferences_cleared": cleared,
                    "templates": self.template_payload(),
                }
            )
        except ValueError as exc:
            return json_response({"error": "invalid_template", "message": str(exc)})
        except Exception as exc:
            logger.exception(f"[HTML渲染] WebUI 删除自定义模板失败: {exc}")
            return json_response(
                {"error": "delete_failed", "message": "自定义模板删除失败"}
            )

    def clear_removed_template_references(self, name: str) -> int:
        cleared = 0
        if str(self.config.get("default_template", "") or "") == name:
            self._save_runtime_config({"default_template": ""})
            cleared += 1
        for user_id, template in list(self.templates.user_defaults.items()):
            if template == name:
                self.templates.user_defaults.pop(user_id, None)
                cleared += 1
        cleared += self.preferences.clear_template(name)
        return cleared

    async def duplicate_template(self):
        body = await self.request_body()
        try:
            metadata = self.templates.manager.duplicate_template(
                str(body.get("source", "") or "").strip(),
                str(body.get("target", "") or "").strip(),
                display_name=str(body.get("display_name", "") or ""),
            )
            self.templates.refresh_schema_options()
            return json_response(
                {
                    "ok": True,
                    "metadata": metadata,
                    "templates": self.template_payload(),
                }
            )
        except ValueError as exc:
            return json_response({"error": "invalid_template", "message": str(exc)})
        except Exception as exc:
            logger.exception(f"[HTML渲染] WebUI 复制模板失败: {exc}")
            return json_response(
                {"error": "duplicate_failed", "message": "模板复制失败"}
            )

    async def export_templates(self):
        templates = [
            {
                "name": name,
                "html": self.templates.manager.load_template(name),
                "metadata": self.templates.manager.get_template_metadata(name),
            }
            for name in self.templates.manager.get_custom_templates()
        ]
        return json_response({"ok": True, "schema_version": 1, "templates": templates})

    async def import_templates(self):
        body = await self.request_body()
        items = body.get("templates")
        if not isinstance(items, list) or len(items) > 50:
            return json_response({"error": "invalid_import", "message": "导入数据无效"})
        imported: list[str] = []
        try:
            prepared = [self._prepare_import(item) for item in items]
            for item in prepared:
                self.templates.manager.save_custom_template(
                    item["name"],
                    item["html"],
                    display_name=item["display_name"],
                    description=item["description"],
                    base_template=item["base_template"],
                )
                imported.append(item["name"])
            self.templates.refresh_schema_options()
            return json_response(
                {
                    "ok": True,
                    "imported": imported,
                    "templates": self.template_payload(),
                }
            )
        except ValueError as exc:
            return json_response(
                {"error": "invalid_import", "message": str(exc), "imported": imported}
            )

    def _prepare_import(self, item: object) -> dict:
        if not isinstance(item, dict):
            raise ValueError("模板条目格式无效")
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        name = self.templates.manager.validate_template_name(
            str(item.get("name", "") or "")
        )
        if name in self.templates.manager.get_builtin_templates():
            raise ValueError(f"不能覆盖内置模板: {name}")
        return {
            "name": name,
            "html": self.templates.manager.validate_custom_html(
                str(item.get("html", "") or "")
            ),
            "display_name": str(metadata.get("display_name", "") or ""),
            "description": str(metadata.get("description", "") or ""),
            "base_template": str(metadata.get("base_template", "classic") or "classic"),
        }

    async def preview(self):
        body = await self.request_body()
        content = str(body.get("content", "") or "")
        template_name = str(body.get("template", "") or "").strip()
        layout = normalize_layout(body.get("layout", "auto"))
        style_values = body.get("style_values", {})
        draft_html = body.get("template_html")
        base_template = str(body.get("base_template", "classic") or "classic").strip()
        if not content.strip():
            return json_response(
                {"error": "invalid_content", "message": "预览内容不能为空"}
            )
        if layout not in {"auto", "single"}:
            return json_response({"error": "invalid_layout", "message": "布局选项无效"})
        if not isinstance(style_values, dict):
            return json_response({"error": "invalid_config", "message": "排版参数无效"})
        try:
            render_template, override = self._preview_template(
                template_name, base_template, draft_html
            )
            style_owner = (
                template_name if self.templates.has(template_name) else render_template
            )
            metadata = self.templates.manager.get_template_metadata(style_owner)
            normalized_styles = self.config.normalize_style_values(
                style_values,
                {str(key) for key in metadata.get("css_variables", [])},
            )
            rendered = await self.pipeline.render(
                content,
                render_template,
                None,
                False,
                layout=layout,
                style_overrides=normalized_styles,
                template_html_override=override,
            )
            images = self._encode_images(self.actions.extract_images(rendered))
            if not images:
                return json_response(
                    {"error": "browser_error", "message": "浏览器未生成预览图片"}
                )
            return json_response(
                {
                    "ok": True,
                    "images": images,
                    "warnings": self.actions.extract_warnings(rendered),
                    "metrics": dict(getattr(rendered, "metrics", {}) or {}),
                }
            )
        except ValueError as exc:
            return json_response({"error": "invalid_template", "message": str(exc)})
        except RenderFailure as exc:
            return json_response(
                {"error": exc.code or "render_failed", "message": exc.message}
            )
        except Exception as exc:
            logger.exception(f"[HTML渲染] WebUI 生成预览失败: {exc}")
            return json_response({"error": "preview_failed", "message": "预览生成失败"})

    def _preview_template(
        self, template_name: str, base_template: str, draft_html
    ) -> tuple[str, str | None]:
        if draft_html is None:
            if not self.templates.has(template_name):
                raise ValueError("模板不存在")
            return template_name, None
        override = self.templates.manager.validate_custom_html(str(draft_html))
        if self.templates.has(template_name):
            return template_name, override
        if base_template in self.templates.manager.get_builtin_templates():
            return base_template, override
        raise ValueError("基础模板不存在")

    @staticmethod
    def _encode_images(images: list) -> list[str]:
        encoded_images = []
        for image in images:
            path = str(getattr(image, "path", "") or "")
            if not path or not os.path.isfile(path):
                continue
            mime = {
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(os.path.splitext(path)[1].lower(), "image/jpeg")
            with open(path, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("ascii")
            encoded_images.append(f"data:{mime};base64,{encoded}")
        return encoded_images

    async def status(self):
        return json_response({"ok": True, "status": self.diagnostics.safe_status()})
