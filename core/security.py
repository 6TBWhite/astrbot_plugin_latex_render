from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlparse


ALLOWED_TAGS = {
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "b",
    "em",
    "i",
    "del",
    "s",
    "blockquote",
    "ul",
    "ol",
    "li",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "hr",
    "a",
    "span",
    "div",
    # Built-in novel template semantic tags.
    "q",
    "inner",
    "act",
    "scene",
    "aside",
}

VOID_TAGS = {"br", "hr"}
DROP_CONTENT_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "template",
    "noscript",
}
GLOBAL_ATTRIBUTES = {"title"}
TAG_ATTRIBUTES = {
    "a": {"href"},
    "th": {"align", "colspan", "rowspan"},
    "td": {"align", "colspan", "rowspan"},
    "ol": {"start"},
    "div": {"class"},
    "span": {"class"},
}
SAFE_CLASSES = {"astr-math-inline", "astr-math-block"}
SAFE_LINK_SCHEMES = {"", "http", "https", "mailto"}


class _SafeHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self._drop_depth = 0
        self._open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth or tag not in ALLOWED_TAGS:
            return

        clean_attrs: list[tuple[str, str]] = []
        permitted = GLOBAL_ATTRIBUTES | TAG_ATTRIBUTES.get(tag, set())
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = raw_value or ""
            if name.startswith("on") or name not in permitted:
                continue
            if name == "class":
                classes = [item for item in value.split() if item in SAFE_CLASSES]
                if not classes:
                    continue
                value = " ".join(classes)
            elif name == "href":
                parsed = urlparse(value.strip())
                if parsed.scheme.lower() not in SAFE_LINK_SCHEMES:
                    continue
            elif name in {"colspan", "rowspan", "start"}:
                if not value.isdigit():
                    continue
                value = str(max(1, min(int(value), 100)))
            elif name == "align":
                value = value.lower()
                if value not in {"left", "center", "right"}:
                    continue
            clean_attrs.append((name, value))

        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in clean_attrs
        )
        self.output.append(f"<{tag}{rendered_attrs}>")
        if tag not in VOID_TAGS:
            self._open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            if self._drop_depth:
                self._drop_depth -= 1
            return
        if self._drop_depth or tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag not in self._open_tags:
            return
        while self._open_tags:
            current = self._open_tags.pop()
            self.output.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str):
        if not self._drop_depth:
            self.output.append(data)

    def handle_entityref(self, name: str):
        if not self._drop_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str):
        if not self._drop_depth:
            self.output.append(f"&#{name};")

    def close(self):
        super().close()
        while self._open_tags:
            self.output.append(f"</{self._open_tags.pop()}>")


def sanitize_html_fragment(fragment: str) -> str:
    """Allow safe Markdown HTML and the plugin's semantic/math tags only."""

    parser = _SafeHTMLParser()
    parser.feed(fragment or "")
    parser.close()
    return "".join(parser.output)
