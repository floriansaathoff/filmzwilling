"""Generated SVG placeholder posters."""

from __future__ import annotations

import hashlib
import textwrap
from html import escape

PALETTE = (
    ("#1f2937", "#4f46e5"),
    ("#1e293b", "#0ea5e9"),
    ("#27272a", "#e11d48"),
    ("#1c1917", "#f59e0b"),
    ("#172554", "#22c55e"),
    ("#2e1065", "#a855f7"),
)


def placeholder_svg(title: str, year: int | None = None) -> str:
    """A 2:3 poster with the title wrapped over several lines and a colour derived from it."""
    digest = int(hashlib.md5(title.encode("utf-8")).hexdigest()[:8], 16)
    bg, accent = PALETTE[digest % len(PALETTE)]
    lines = textwrap.wrap(title, width=16)[:6] or [title]
    start_y = 210 - (len(lines) - 1) * 19
    spans = "".join(
        f'<tspan x="171" y="{start_y + i * 38}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    year_text = (
        f'<text x="171" y="440" font-size="26" fill="#cbd5e1" text-anchor="middle">{year}</text>'
        if year
        else ""
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="342" height="513" viewBox="0 0 342 513">'
        f'<rect width="342" height="513" fill="{bg}"/>'
        f'<rect x="0" y="0" width="342" height="10" fill="{accent}"/>'
        f'<rect x="0" y="503" width="342" height="10" fill="{accent}"/>'
        '<text font-family="system-ui, sans-serif" font-size="30" font-weight="700" '
        f'fill="#f8fafc" text-anchor="middle">{spans}</text>'
        f"{year_text}"
        "</svg>"
    )
