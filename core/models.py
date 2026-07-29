from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserRenderResult:
    """Low-level Chromium rendering result."""

    success: bool
    paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""

    def __bool__(self) -> bool:
        return self.success


@dataclass
class RenderResult:
    """Plugin-level result consumed by commands and LLM tools."""

    images: list[Any]
    template: str
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.images)


class RenderFailure(RuntimeError):
    """User-safe categorized rendering failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
