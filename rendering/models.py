from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RenderOptions:
    """Browser capture options shared by the renderer phases."""

    html_content: str
    output_image_path: str
    scale: int = 2
    width: int = 600
    is_gif: bool = False
    duration: float = 3.0
    fps: int = 15
    layout: str = "auto"
    max_page_height: int = 3200
    max_pages: int = 8
    max_output_bytes: int = 6 * 1024 * 1024
    show_page_numbers: bool = True
    page_number_bottom_margin: int = 20
    allow_remote_assets: bool = False
    fixed_page_size: dict | None = None


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


@dataclass
class RenderRuntimeSnapshot:
    """High-level queue, cooldown, and last-result state."""

    active_renders: int = 0
    queued_renders: int = 0
    last_metrics: dict[str, Any] = field(default_factory=dict)
    last_error: dict[str, Any] = field(default_factory=dict)
    cooldown_seconds: int = 0
