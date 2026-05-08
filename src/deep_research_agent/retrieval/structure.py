"""Size-first source routing (ADR 0007).

For long sources (>= ~8K tokens), we extract a structured view so the
analyzer doesn't have to chew through the whole document in one shot:

    StructuredContent:
      - abstract (first paragraph before any header)
      - section_headers (ordered list)
      - first_paragraph_of_each_section
      - table_of_contents (h2/h3 only)
      - figure_captions (lines starting with "Figure N:" / "Fig. N.")

`load_source_section(markdown, section_title)` reverses this: given the
full markdown and a header string, it returns just that section's body
(up to the next header of equal or higher level).

Token counting is a rough `chars/4` approximation — tiktoken-accurate
counting isn't load-bearing for the size threshold decision.
"""

from __future__ import annotations

import re

from ..schemas.source import StructuredContent

LONG_SOURCE_TOKEN_THRESHOLD = 8000
# Rough chars-per-token estimate; English prose averages ~4.
_CHARS_PER_TOKEN = 4

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_FIGURE_RE = re.compile(r"^(?:\*\*)?(?:Figure|Fig\.?)\s*\d+[:.].*$", re.MULTILINE | re.IGNORECASE)


def rough_token_count(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def is_long_source(markdown: str) -> bool:
    return rough_token_count(markdown) >= LONG_SOURCE_TOKEN_THRESHOLD


def _first_paragraph(text: str) -> str:
    """Return the first non-empty paragraph of `text`, stripped."""
    for para in re.split(r"\n\s*\n", text.strip()):
        p = para.strip()
        if p:
            return p
    return ""


def build_structured_content(title: str, markdown: str) -> StructuredContent:
    """Extract a structured view from long markdown.

    The caller should only invoke this when `is_long_source()` returns
    True; on short sources the analyzer reads the full content directly
    and a structured view is wasted work.
    """
    headers: list[tuple[int, str, int, int]] = []  # (level, title, match_start, match_end)
    for m in _HEADER_RE.finditer(markdown):
        level = len(m.group(1))
        headers.append((level, m.group(2).strip(), m.start(), m.end()))

    # Abstract: the opening content before the first level-2+ header. If
    # the doc leads with an H1 title, skip it — the interesting opening
    # text is the paragraph between the title and the first section.
    first_section_start = next((h[2] for h in headers if h[0] >= 2), len(markdown))
    if headers and headers[0][0] == 1 and headers[0][2] == 0:
        abstract_region = markdown[headers[0][3] : first_section_start]
    else:
        abstract_region = markdown[:first_section_start]
    abstract = _first_paragraph(abstract_region)

    section_headers = [h[1] for h in headers]
    toc = [h[1] for h in headers if h[0] in (2, 3)]

    first_para_by_section: dict[str, str] = {}
    for i, (_, name, _, body_start) in enumerate(headers):
        body_end = headers[i + 1][2] if i + 1 < len(headers) else len(markdown)
        body = markdown[body_start:body_end]
        first_para_by_section[name] = _first_paragraph(body)[:800]

    figures = [m.group(0).strip()[:200] for m in _FIGURE_RE.finditer(markdown)]

    return StructuredContent(
        title=title,
        abstract=abstract[:1500] or None,
        section_headers=section_headers,
        first_paragraph_of_each_section=first_para_by_section,
        table_of_contents=toc,
        figure_captions=figures[:40],
    )


def load_source_section(markdown: str, section_title: str) -> str | None:
    """Return the body of the section whose header equals `section_title`.

    Header matching is case-insensitive and tolerant of surrounding
    whitespace. Section body ends at the next header of equal-or-higher
    level, or at EOF. Returns None when no matching section exists.
    """
    target = section_title.strip().casefold()
    matches = list(_HEADER_RE.finditer(markdown))
    for i, m in enumerate(matches):
        if m.group(2).strip().casefold() == target:
            my_level = len(m.group(1))
            start = m.end()
            end = len(markdown)
            for j in range(i + 1, len(matches)):
                if len(matches[j].group(1)) <= my_level:
                    end = matches[j].start()
                    break
            return markdown[start:end].strip()
    return None


def render_outline(content: StructuredContent) -> str:
    """Render a StructuredContent into a compact markdown outline.

    Used by the analyzer user message for long sources — the analyzer
    sees the shape of the document and the first paragraph of each
    section without the full body. If it needs more, a tool call to
    `load_source_section` can pull the specific section.
    """
    lines: list[str] = [f"# {content.title}"]
    if content.abstract:
        lines.append("")
        lines.append("**Abstract / opening:**")
        lines.append(content.abstract)
    if content.section_headers:
        lines.append("")
        lines.append("**Section outline:**")
        for name in content.section_headers:
            lines.append(f"- {name}")
            preview = content.first_paragraph_of_each_section.get(name)
            if preview:
                # Indent to make the preview read as belonging to the header.
                lines.append(f"  > {preview}")
    if content.figure_captions:
        lines.append("")
        lines.append("**Figure captions:**")
        for cap in content.figure_captions:
            lines.append(f"- {cap}")
    return "\n".join(lines)
