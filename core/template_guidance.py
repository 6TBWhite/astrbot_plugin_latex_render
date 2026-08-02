import re

from astrbot.api import logger

from .template_manager import TemplateManager


class TemplateGuidanceBuilder:
    """Build bounded, agent-facing guidance from live template metadata."""

    DISPLAY_NAME_LIMIT = 80
    DESCRIPTION_LIMIT = 240
    TAG_LIMIT = 6
    TAG_LENGTH_LIMIT = 40
    PROMPT_LIMIT = 1200
    SELECTION_RULE = (
        "选择规则：用户未明确指定样式时，让 latex_render_to_image 的 template "
        "留空以沿用当前模板。"
    )

    def __init__(
        self,
        template_manager: TemplateManager,
        available_templates: list[str],
    ):
        self.template_manager = template_manager
        self.available_templates = [str(name) for name in available_templates]

    @staticmethod
    def _normalize_text(value, limit: int, *, multiline: bool = False) -> str:
        text = str(value or "").strip()
        if multiline:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        else:
            text = re.sub(r"\s+", " ", text)
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}…"

    def _records(self) -> list[dict]:
        records: list[dict] = []
        metadata_getter = getattr(
            self.template_manager,
            "get_template_metadata",
            None,
        )
        for name in self.available_templates:
            metadata: dict = {}
            if callable(metadata_getter):
                try:
                    value = metadata_getter(name)
                    if isinstance(value, dict):
                        metadata = value
                except Exception as exc:
                    logger.warning(
                        f"[HTML渲染] 读取模板 {name} 的 Agent 元数据失败: {exc}"
                    )

            raw_tags = metadata.get("tags", [])
            tags: list[str] = []
            if isinstance(raw_tags, (list, tuple)):
                for raw_tag in raw_tags[: self.TAG_LIMIT]:
                    tag = self._normalize_text(raw_tag, self.TAG_LENGTH_LIMIT)
                    if tag:
                        tags.append(tag)

            source = (
                "custom"
                if str(metadata.get("source", "builtin")).lower() == "custom"
                else "builtin"
            )
            records.append(
                {
                    "name": name,
                    "display_name": self._normalize_text(
                        metadata.get("display_name", name),
                        self.DISPLAY_NAME_LIMIT,
                    ),
                    "description": self._normalize_text(
                        metadata.get("description", ""),
                        self.DESCRIPTION_LIMIT,
                    ),
                    "scene": self._normalize_text(
                        metadata.get("scene", ""),
                        self.TAG_LENGTH_LIMIT,
                    ),
                    "source": source,
                    "tags": tags,
                }
            )
        return records

    def _builtin_prompt(self, record: dict) -> str:
        if record["source"] != "builtin":
            return ""
        prompt_getter = getattr(
            self.template_manager,
            "extract_builtin_prompt",
            None,
        )
        if not callable(prompt_getter):
            return ""
        try:
            prompt = prompt_getter(record["name"])
        except Exception as exc:
            logger.warning(
                f"[HTML渲染] 读取模板 {record['name']} 的内置规范失败: {exc}"
            )
            return ""
        return self._normalize_text(
            prompt,
            self.PROMPT_LIMIT,
            multiline=True,
        )

    def _format_detail(self, record: dict, current_template: str) -> str:
        source_label = "自定义" if record["source"] == "custom" else "内置"
        lines = [
            f"模板：{record['name']}",
            f"显示名称：{record['display_name']}",
            f"来源：{source_label}",
            f"是否为当前模板：{'是' if record['name'] == current_template else '否'}",
        ]
        optional_fields = (
            ("场景", record["scene"]),
            ("用途", record["description"]),
            ("标签", "、".join(record["tags"])),
        )
        lines.extend(f"{label}：{value}" for label, value in optional_fields if value)

        prompt = self._builtin_prompt(record)
        if prompt:
            lines.extend(["内容规范：", prompt])
        lines.extend(
            [
                f'latex_render_to_image 参数：template="{record["name"]}"',
                self.SELECTION_RULE,
            ]
        )
        return "\n".join(lines)

    def _format_catalog(
        self,
        records: list[dict],
        current_template: str,
        *,
        compact: bool,
    ) -> str:
        names = [record["name"] for record in records]
        effective_current = current_template if current_template in names else "未设置"
        lines = [f"当前模板：{effective_current}", "可用渲染模板："]
        for record in records:
            source_label = "自定义" if record["source"] == "custom" else "内置"
            current_label = "，当前" if record["name"] == current_template else ""
            description = record["description"] or "暂无说明"
            if compact:
                description = self._normalize_text(description, 120)
            summary = (
                f"- {record['name']}（{record['display_name']}，"
                f"{source_label}{current_label}）：{description}"
            )
            if not compact and record["tags"]:
                summary += f"；标签：{'、'.join(record['tags'])}"
            lines.append(summary)
        lines.append(self.SELECTION_RULE)
        return "\n".join(lines)

    def build(
        self,
        current_template: str = "",
        template: str = "",
        *,
        compact: bool = False,
    ) -> str:
        records = self._records()
        if not records:
            return "当前没有可用的渲染模板，请检查插件模板目录。"

        requested_template = str(template or "").strip()
        names = [record["name"] for record in records]
        if not requested_template:
            return self._format_catalog(
                records,
                current_template,
                compact=compact,
            )

        record = next(
            (item for item in records if item["name"] == requested_template),
            None,
        )
        if record is not None:
            return self._format_detail(record, current_template)

        safe_name = self._normalize_text(requested_template, self.DISPLAY_NAME_LIMIT)
        return f"未找到模板：{safe_name}\n当前可用模板：{'、'.join(names)}"
