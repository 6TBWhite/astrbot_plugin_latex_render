"""Persistent per-conversation rendering preferences."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from astrbot.api import logger

from .config import normalize_layout


class PreferenceStore:
    """Load and atomically persist schema-v1 rendering preferences."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[str, dict[str, str]] = {}

    def load(self) -> None:
        self.entries = {}
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
            if not isinstance(entries, dict):
                raise ValueError("entries 不是对象")
            for key, value in entries.items():
                cleaned = self._clean_entry(key, value)
                if cleaned:
                    self.entries[key] = cleaned
            logger.info(f"[HTML渲染] 已加载 {len(self.entries)} 条用户渲染偏好")
        except Exception as exc:
            logger.warning(f"[HTML渲染] 用户偏好文件损坏，已忽略: {exc}")
            self.entries = {}

    @staticmethod
    def _clean_entry(key: object, value: object) -> dict[str, str]:
        if not isinstance(key, str) or not isinstance(value, dict):
            return {}
        cleaned: dict[str, str] = {}
        template = str(value.get("template", "") or "").strip()
        layout = normalize_layout(value.get("layout", ""))
        theme = str(value.get("theme", "") or "").strip()
        if template:
            cleaned["template"] = template
        if layout in {"auto", "single"}:
            cleaned["layout"] = layout
        if theme:
            cleaned["theme"] = theme
        return cleaned

    def save(self) -> None:
        temp_path = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schema_version": 1, "entries": self.entries}
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception as exc:
            logger.warning(f"[HTML渲染] 保存用户偏好失败: {exc}")
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def get(self, key: str) -> dict[str, str]:
        return self.entries.get(key, {})

    def update(self, key: str, **values: str) -> None:
        entry = self.entries.setdefault(key, {})
        for name, value in values.items():
            if value:
                entry[name] = value
            else:
                entry.pop(name, None)
        if not entry:
            self.entries.pop(key, None)
        self.save()

    def reset(self, key: str) -> bool:
        removed = self.entries.pop(key, None) is not None
        if removed:
            self.save()
        return removed

    def clear_template(self, template_name: str) -> int:
        cleared = 0
        for key, entry in list(self.entries.items()):
            if entry.get("template") != template_name:
                continue
            entry.pop("template", None)
            cleared += 1
            if not entry:
                self.entries.pop(key, None)
        if cleared:
            self.save()
        return cleared
