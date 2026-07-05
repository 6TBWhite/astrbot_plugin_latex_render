# text_processing.py
# 文本检测、Markdown 渲染、对话格式化、换行处理

import html as html_lib
import re
from typing import List, Optional, Tuple

from astrbot.api import logger

# ==================== Markdown 渲染支持 ====================

_markdown_renderer = None
MARKDOWN_AVAILABLE = False
_CODE_TOKEN_PREFIX = "ASTRCODETOKEN"
_INLINE_MATH_TOKEN_PREFIX = "ASTRINLINEMATHTOKEN"
_FENCED_CODE_PATTERN = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_PATTERN = re.compile(r"`[^`\n]+`")
_DISPLAY_MATH_PATTERN = re.compile(
    r"(?<!\\)\$\$[\s\S]+?(?<!\\)\$\$"
    r"|\\\[[\s\S]+?\\\]"
    r"|\\begin\{([a-zA-Z*]+)\}[\s\S]+?\\end\{\1\}",
    re.DOTALL,
)
_INLINE_MATH_PATTERNS = [
    re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$(?!\$)"),
    re.compile(r"\\\(.+?\\\)"),
]

def _make_placeholder(prefix: str, index: int) -> str:
    return f"{prefix}{index}END"

def _protect_segments(text: str, patterns: List[re.Pattern], prefix: str) -> Tuple[str, List[str]]:
    segments: List[str] = []

    def _replace(match: re.Match) -> str:
        segments.append(match.group(0))
        return _make_placeholder(prefix, len(segments) - 1)

    for pattern in patterns:
        text = pattern.sub(_replace, text)

    return text, segments

def _restore_segments(text: str, segments: List[str], prefix: str) -> str:
    for idx, segment in enumerate(segments):
        text = text.replace(_make_placeholder(prefix, idx), segment)
    return text

def _escape_math_fragment(fragment: str) -> str:
    return html_lib.escape(fragment, quote=False)

def _strip_display_delimiters(matched: str) -> str:
    r"""Strip display-math delimiters ($$…$$ or \[…\]), keeping inner LaTeX.

    For \begin{env}…\end{env} the environment IS the math, so keep as-is.
    """
    if matched.startswith("$$"):
        return matched[2:-2]
    if matched.startswith("\\["):
        return matched[2:-2]
    return matched

def _strip_inline_delimiters(matched: str) -> str:
    r"""Strip inline-math delimiters ($…$ or \(…\)), keeping inner LaTeX."""
    if matched.startswith("\\("):
        return matched[2:-2]
    return matched[1:-1]

def _prepare_math_for_markdown(text: str) -> Tuple[str, List[str]]:
    """
    Protect code first, then keep LaTeX intact across Markdown rendering.
    Display math becomes raw HTML blocks before Markdown parsing;
    inline math is restored after Markdown so it can live inside emphasis, links, etc.
    """
    text, code_segments = _protect_segments(
        text, [_FENCED_CODE_PATTERN, _INLINE_CODE_PATTERN], _CODE_TOKEN_PREFIX
    )

    text = _DISPLAY_MATH_PATTERN.sub(
        lambda m: (
            "\n"
            f'<div class="astr-math-block">\\[{_escape_math_fragment(_strip_display_delimiters(m.group(0)))}\\]</div>'
            "\n"
        ),
        text,
    )

    inline_math_segments: List[str] = []

    def _replace_inline_math(match: re.Match) -> str:
        inline_math_segments.append(
            f'<span class="astr-math-inline">\\({_escape_math_fragment(_strip_inline_delimiters(match.group(0)))}\\)</span>'
        )
        return _make_placeholder(_INLINE_MATH_TOKEN_PREFIX, len(inline_math_segments) - 1)

    for pattern in _INLINE_MATH_PATTERNS:
        text = pattern.sub(_replace_inline_math, text)

    text = _restore_segments(text, code_segments, _CODE_TOKEN_PREFIX)
    return text, inline_math_segments

try:
    import mistune

    if hasattr(mistune, "create_markdown"):
        # mistune 2.x / 3.x
        try:
            _markdown_renderer = mistune.create_markdown(
                escape=False, hard_wrap=True, plugins=["table", "strikethrough"]
            )
        except (TypeError, KeyError):
            try:
                _markdown_renderer = mistune.create_markdown(
                    escape=False, hard_wrap=True
                )
            except TypeError:
                _markdown_renderer = mistune.create_markdown()
                logger.warning("HTML渲染插件: 当前 mistune 版本可能不保留内联 HTML")
    elif hasattr(mistune, "Markdown"):
        # mistune 0.x
        _markdown_renderer = mistune.Markdown()
    else:
        _markdown_renderer = mistune.html

    MARKDOWN_AVAILABLE = True
    logger.info(
        f"HTML渲染插件: mistune {getattr(mistune, '__version__', 'unknown')} 初始化成功"
    )
except ImportError:
    MARKDOWN_AVAILABLE = False
    logger.warning(
        "HTML渲染插件: mistune 未安装，Markdown 渲染功能将不可用。"
        "可通过 pip install mistune 安装。"
    )

# ==================== 文本检测 ====================

def contains_math(text: str) -> bool:
    """Detect common LaTeX/math delimiters outside code blocks."""
    if not text:
        return False

    protected_text, _ = _protect_segments(
        text, [_FENCED_CODE_PATTERN, _INLINE_CODE_PATTERN], _CODE_TOKEN_PREFIX
    )
    return any(
        pattern.search(protected_text)
        for pattern in (_DISPLAY_MATH_PATTERN, *_INLINE_MATH_PATTERNS)
    )

# ==================== 换行与格式处理 ====================

def preserve_newlines(text: str) -> str:
    """
    保留文本中的换行符，将 \\n 转换为 <br> 或 <p> 标签。
    若已包含 HTML 块级标签则直接返回。
    """
    if re.search(r"<(p|div|br|table|ul|ol|li|h[1-6])\b", text, re.IGNORECASE):
        return text

    lines = text.split("\n")
    if len(lines) == 1:
        return text

    result_parts: List[str] = []
    current_paragraph: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped:
            current_paragraph.append(stripped)
        else:
            if current_paragraph:
                result_parts.append("<br>".join(current_paragraph))
                current_paragraph = []

    if current_paragraph:
        result_parts.append("<br>".join(current_paragraph))

    if len(result_parts) > 1:
        return "".join(f"<p>{p}</p>" for p in result_parts)
    elif result_parts:
        return result_parts[0]
    else:
        return text

def nl2br(html: str) -> str:
    """
    统一换行处理：保留空行（\\n\\n → <br><br>），
    消除标签间缩进换行，保护 <style>/<script>/<pre>/<code>。
    """
    if not html:
        return html

    html = html.replace("\r\n", "\n").replace("\r", "\n")

    protected_blocks: List[str] = []

    def _protect(m: re.Match) -> str:
        protected_blocks.append(m.group(0))
        return f"__ASTR_LATEX_RENDER_PROTECTED_{len(protected_blocks) - 1}__"

    html = re.sub(
        r"<style\b[^>]*>[\s\S]*?</style>", _protect, html, flags=re.IGNORECASE
    )
    html = re.sub(
        r"<script\b[^>]*>[\s\S]*?</script>", _protect, html, flags=re.IGNORECASE
    )
    html = re.sub(
        r"<pre\b[^>]*>[\s\S]*?</pre>", _protect, html, flags=re.IGNORECASE
    )
    html = re.sub(
        r"<code\b[^>]*>[\s\S]*?</code>", _protect, html, flags=re.IGNORECASE
    )

    # 消除标签间单行缩进换行
    html = re.sub(r">[ \t]*\n[ \t]*<", "><", html)

    parts = re.split(r"(<[^>]+?>)", html)
    out: List[str] = []

    for seg in parts:
        if seg.startswith("<"):
            out.append(seg)
            continue

        seg = re.sub(r"\n{3,}", "\n\n", seg)

        if seg.strip() == "":
            if seg.count("\n") >= 2:
                out.append("<br><br>")
            continue

        seg = seg.replace("\n\n", "<br><br>")
        seg = seg.replace("\n", "<br>")
        out.append(seg)

    result = "".join(out)
    result = re.sub(r"(?:<br>){3,}", "<br><br>", result)

    for i, block in enumerate(protected_blocks):
        result = result.replace(f"__ASTR_LATEX_RENDER_PROTECTED_{i}__", block)

    return result

# ==================== Markdown / 表格 转换 ====================

def markdown_to_html(text: str) -> str:
    """将 Markdown 转换为 HTML"""
    if not MARKDOWN_AVAILABLE or _markdown_renderer is None:
        return preserve_newlines(text)

    try:
        prepared_text, inline_math_segments = _prepare_math_for_markdown(text)
        html = _markdown_renderer(prepared_text)
        html = _restore_segments(html, inline_math_segments, _INLINE_MATH_TOKEN_PREFIX)
        logger.debug(
            f"[Markdown] 渲染成功，输入长度: {len(text)}, 输出长度: {len(html)}"
        )
        return html
    except Exception as e:
        logger.error(f"Markdown 渲染失败: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return preserve_newlines(text)

def convert_markdown_tables(text: str) -> str:
    """
    将 Markdown 表格转换为 HTML 表格（用于混合内容场景）。

    注意：此函数当前未被调用，保留作为可选工具。
    """
    lines = text.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if "|" in line and i + 1 < len(lines):
            next_line = lines[i + 1]
            if re.match(
                r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", next_line
            ):
                table_lines = [line, next_line]
                i += 2
                while i < len(lines) and "|" in lines[i]:
                    if not re.match(
                        r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", lines[i]
                    ):
                        table_lines.append(lines[i])
                    i += 1
                result.append(_parse_markdown_table(table_lines))
                continue

        result.append(line)
        i += 1

    return "\n".join(result)

def _parse_markdown_table(lines: List[str]) -> str:
    """解析 Markdown 表格并生成 HTML"""
    if len(lines) < 2:
        return "\n".join(lines)

    def parse_row(line: str) -> List[str]:
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [cell.strip() for cell in line.split("|")]

    header_cells = parse_row(lines[0])
    body_rows = [parse_row(line) for line in lines[2:]]

    html = [
        '<table style="border-collapse:collapse;width:100%;margin:1em 0;font-size:14px;">'
    ]

    html.append("<thead><tr>")
    for cell in header_cells:
        html.append(
            f'<th style="border:1px solid #d4c4a8;padding:8px 12px;'
            f'background:#f5f0e6;text-align:left;font-weight:600;">{cell}</th>'
        )
    html.append("</tr></thead>")

    html.append("<tbody>")
    for row in body_rows:
        html.append("<tr>")
        for cell in row:
            html.append(
                f'<td style="border:1px solid #d4c4a8;padding:8px 12px;'
                f'background:#fffef9;">{cell}</td>'
            )
        html.append("</tr>")
    html.append("</tbody></table>")

    return "".join(html)
