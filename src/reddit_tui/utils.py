"""Small formatting helpers."""
from __future__ import annotations

import time


def escape_markup(text: str) -> str:
    """Escape Textual/Rich markup so user content can't break rendering.

    Rich/Textual treat ``[`` as the start of a markup tag. The standard
    escape is to double it. We don't need to escape ``]``.
    """
    if not text:
        return ""
    return text.replace("[", "\\[")


def format_score(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def format_age(created_utc: float) -> str:
    if not created_utc:
        return "?"
    delta = max(0, int(time.time() - created_utc))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 86400 * 30:
        return f"{delta // 86400}d"
    if delta < 86400 * 365:
        return f"{delta // (86400 * 30)}mo"
    return f"{delta // (86400 * 365)}y"
