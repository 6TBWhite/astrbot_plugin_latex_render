"""Image post-processing applied after browser capture."""

import os

from astrbot.api import logger

try:
    from PIL import Image as PILImage, ImageDraw, ImageFont, ImageStat

    PIL_AVAILABLE = True
except ImportError:
    PILImage = ImageDraw = ImageFont = ImageStat = None
    PIL_AVAILABLE = False
    logger.warning(
        "HTML渲染插件: Pillow 未安装，GIF 动画与图片后处理功能将不可用。"
        "可通过 pip install Pillow 安装。"
    )


def _page_number_font_size(scale: int) -> int:
    return max(14, 14 * max(1, int(scale)))


def _load_page_number_font(size: int):
    candidates = (
        "DejaVuSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _page_number_position(
    image_size: tuple[int, int],
    text_bbox: tuple[int, int, int, int],
    scale: int,
    bottom_margin: int = 20,
) -> tuple[int, int]:
    image_width, image_height = image_size
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    scaled_bottom_margin = max(1, int(bottom_margin)) * max(1, int(scale))
    x = (image_width - text_width) // 2 - text_bbox[0]
    y = image_height - scaled_bottom_margin - text_height - text_bbox[1]
    return max(0, x), max(0, y)


def _page_number_color(
    image,
    text_box: tuple[int, int, int, int],
    scale: int,
) -> tuple[int, int, int, int]:
    padding = 4 * max(1, int(scale))
    sample_box = (
        max(0, text_box[0] - padding),
        max(0, text_box[1] - padding),
        min(image.width, text_box[2] + padding),
        min(image.height, text_box[3] + padding),
    )
    luminance = ImageStat.Stat(image.crop(sample_box).convert("L")).mean[0]
    if luminance >= 145:
        return (42, 42, 42, 190)
    return (246, 242, 232, 220)


def _add_page_number(
    path: str,
    page_number: int,
    page_count: int,
    scale: int,
    bottom_margin: int = 20,
) -> None:
    if not PIL_AVAILABLE or page_count <= 1:
        return
    try:
        with PILImage.open(path) as source:
            image = source.convert("RGB")
            font = _load_page_number_font(_page_number_font_size(scale))
            label = f"— {page_number} / {page_count} —"
            measure = ImageDraw.Draw(image)
            bbox = measure.textbbox((0, 0), label, font=font)
            x, y = _page_number_position(
                image.size, bbox, scale, bottom_margin=bottom_margin
            )
            text_box = (
                x + bbox[0],
                y + bbox[1],
                x + bbox[2],
                y + bbox[3],
            )
            color = _page_number_color(image, text_box, scale)
            overlay = PILImage.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).text((x, y), label, font=font, fill=color)
            rendered = PILImage.alpha_composite(image.convert("RGBA"), overlay)
            rendered.convert("RGB").save(path, "JPEG", quality=90, optimize=True)
    except Exception as exc:
        logger.warning(f"[HTML渲染] 添加页码失败: {exc}")


def _add_continuation_marker(
    path: str, continues_from_previous: bool, continues_to_next: bool
) -> None:
    if not PIL_AVAILABLE or not (continues_from_previous or continues_to_next):
        return
    try:
        with PILImage.open(path) as source:
            image = source.convert("RGB")
            draw = ImageDraw.Draw(image)
            if continues_from_previous:
                draw.rounded_rectangle(
                    (14, 12, 124, 36),
                    radius=5,
                    fill=(255, 255, 255),
                    outline=(190, 190, 190),
                )
                draw.text((22, 18), "continued", fill=(80, 80, 80))
            if continues_to_next:
                y = max(12, image.height - 38)
                draw.rounded_rectangle(
                    (14, y, 132, y + 24),
                    radius=5,
                    fill=(255, 255, 255),
                    outline=(190, 190, 190),
                )
                draw.text((22, y + 6), "continues...", fill=(80, 80, 80))
            image.save(path, "JPEG", quality=90, optimize=True)
    except Exception as exc:
        logger.warning(f"[HTML渲染] 添加续页标记失败: {exc}")


def _pad_fixed_canvas(
    path: str,
    page_width: int,
    page_height: int,
    top_margin: int,
    scale: int,
) -> None:
    """Place a semantic page slice on a same-size white paper canvas."""

    if not PIL_AVAILABLE:
        raise ValueError("固定纸张分页需要 Pillow")
    pixel_width = max(1, int(page_width * scale))
    pixel_height = max(1, int(page_height * scale))
    y = max(0, int(top_margin * scale))
    with PILImage.open(path) as source:
        slice_image = source.convert("RGB")
        if slice_image.width != pixel_width:
            ratio = pixel_width / max(1, slice_image.width)
            slice_image = slice_image.resize(
                (pixel_width, max(1, int(slice_image.height * ratio))),
                PILImage.Resampling.LANCZOS,
            )
        available_height = max(1, pixel_height - y)
        if slice_image.height > available_height:
            slice_image = slice_image.crop((0, 0, slice_image.width, available_height))
        canvas = PILImage.new("RGB", (pixel_width, pixel_height), "white")
        canvas.paste(slice_image, (0, y))
        canvas.save(path, "JPEG", quality=92, optimize=True)


def _enforce_image_budget(path: str, max_output_bytes: int) -> str | None:
    """Compress an oversized JPEG and report a warning when quality is reduced."""

    if max_output_bytes <= 0 or not os.path.isfile(path):
        return None
    if os.path.getsize(path) <= max_output_bytes:
        return None
    if not PIL_AVAILABLE:
        raise ValueError("图片超过体积上限，且 Pillow 不可用，无法自动压缩")

    with PILImage.open(path) as source:
        image = source.convert("RGB")
        for quality in (84, 78, 72, 66, 60):
            image.save(path, "JPEG", quality=quality, optimize=True)
            if os.path.getsize(path) <= max_output_bytes:
                return f"图片超过体积预算，已将 JPEG 质量调整为 {quality}"

        while (
            os.path.getsize(path) > max_output_bytes
            and image.width > 480
            and image.height > 480
        ):
            image = image.resize(
                (max(1, int(image.width * 0.85)), max(1, int(image.height * 0.85))),
                PILImage.Resampling.LANCZOS,
            )
            image.save(path, "JPEG", quality=66, optimize=True)

    if os.path.getsize(path) > max_output_bytes:
        raise ValueError(
            f"图片压缩后仍有 {os.path.getsize(path)} 字节，超过上限 {max_output_bytes}"
        )
    return "图片超过体积预算，已自动降低分辨率"


def postprocess_paginated_images(
    output_paths: list[str],
    hard_breaks: set[int],
    *,
    fixed_page_size: dict | None,
    width: int,
    scale: int,
    show_page_numbers: bool,
    page_number_bottom_margin: int,
) -> None:
    """Apply fixed canvas, continuation markers, and page numbers."""

    if fixed_page_size:
        for path in output_paths:
            _pad_fixed_canvas(
                path,
                int(fixed_page_size.get("width", width)),
                int(fixed_page_size.get("height", 1123)),
                int(fixed_page_size.get("top_margin", 76)),
                scale,
            )

    for index, path in enumerate(output_paths, start=1):
        _add_continuation_marker(
            path,
            continues_from_previous=(index - 1) in hard_breaks,
            continues_to_next=index in hard_breaks,
        )
    if show_page_numbers and len(output_paths) > 1:
        for index, path in enumerate(output_paths, start=1):
            _add_page_number(
                path,
                index,
                len(output_paths),
                scale,
                bottom_margin=page_number_bottom_margin,
            )


def enforce_image_budgets(
    output_paths: list[str], max_output_bytes: int
) -> list[str]:
    """Enforce output budgets while de-duplicating warning text."""

    warnings: list[str] = []
    for path in output_paths:
        warning = _enforce_image_budget(path, max_output_bytes)
        if warning and warning not in warnings:
            warnings.append(warning)
    return warnings


def _cleanup_output_family(output_image_path: str) -> None:
    directory = os.path.dirname(output_image_path) or "."
    base = os.path.splitext(os.path.basename(output_image_path))[0]
    try:
        for name in os.listdir(directory):
            stem, extension = os.path.splitext(name)
            if extension.lower() not in {".jpg", ".jpeg", ".gif", ".png"}:
                continue
            if stem == base or stem.startswith(f"{base}_p"):
                try:
                    os.remove(os.path.join(directory, name))
                except OSError:
                    pass
    except OSError:
        pass
