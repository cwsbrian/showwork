"""Embed a static Diagram Design HTML file in a Showwork visual section."""

from html.parser import HTMLParser
from pathlib import Path
import re


MAX_DIAGRAM = 512 * 1024


class DiagramParts(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0]
        for match in re.finditer("\n", source):
            self.lines.append(match.end())
        self.svg_start = None
        self.svg_end = None
        self.svg_depth = 0
        self.style_start = None
        self.style_end = None

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "svg":
            if self.svg_depth == 0:
                if self.svg_start is not None:
                    raise ValueError("Diagram Design HTML must contain one main SVG")
                self.svg_start = self.position()
            self.svg_depth += 1
        elif tag == "style" and self.svg_depth == 0 and self.style_start is None:
            self.style_start = self.position()

    def handle_endtag(self, tag):
        if tag == "svg" and self.svg_depth:
            self.svg_depth -= 1
            if self.svg_depth == 0:
                self.svg_end = self.position() + len("</svg>")
        elif tag == "style" and self.svg_depth == 0 and self.style_start is not None and self.style_end is None:
            self.style_end = self.position() + len("</style>")


def embed(source, page_source):
    """Read a standalone static HTML diagram next to the report JSON and return an embeddable fragment."""
    relative = Path(source)
    base = Path(page_source).resolve().parent
    if relative.is_absolute() or not str(relative).endswith(".html"):
        raise ValueError("diagram must be a relative .html file next to the report JSON")
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("diagram must stay inside the report's temporary directory")
    if path.stat().st_size > MAX_DIAGRAM:
        raise ValueError("Diagram Design HTML is too large")
    html = path.read_text(encoding="utf-8")
    if re.search(r"<\s*(script|iframe|object|embed)\b|\bon[a-z]+\s*=|@import\b", html, re.I):
        raise ValueError("Only static Diagram Design HTML can be embedded")
    parts = DiagramParts(html)
    parts.feed(html)
    if parts.svg_start is None or parts.svg_end is None or parts.style_start is None or parts.style_end is None:
        raise ValueError("Diagram Design HTML needs an inline SVG and style")
    svg = html[parts.svg_start:parts.svg_end]
    style = html[parts.style_start:parts.style_end]
    if not re.search(r'<svg\b[^>]*\brole=["\']img["\']', svg, re.I) or not re.search(r"<title\b", svg, re.I):
        raise ValueError("Diagram Design SVG needs an accessible title and role")
    # The report frame already has a title and its own page. Keep only the drawing,
    # preserve the diagram's local scrolling, and use system font fallbacks offline.
    return (style + '<style>body{display:block!important;min-height:0!important;'
            'padding:0!important;margin:0!important;background:transparent!important}'
            '.frame{max-width:none!important;width:100%!important}'
            '.showwork-diagram-hint{display:none;padding:8px 12px;margin:0;'
            'font:12px system-ui;color:#52696b}'
            '@media(max-width:1100px){.showwork-diagram-hint{display:block}}</style>'
            '<div class="frame"><p class="showwork-diagram-hint">↔ Scroll diagram</p>'
            '<div class="diagram-container">' + svg + '</div></div>')
