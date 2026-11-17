"""Repair Arabic text extracted from "visual-order" PDFs.

Some Arabic generators (legacy tools, some CAD/Word export paths) embed glyphs
in display order using presentation-form codepoints. Reading such a PDF yields
mirrored, disjoined text. Detection: any Arabic presentation-form codepoint
(\uFB50-\uFDFF, \uFE70-\uFEFF). Logical-order PDFs (Word, LibreOffice, most modern
exporters) contain no presentation forms and pass through unchanged.
"""

import re
import unicodedata

from bidi.algorithm import get_display

_PRESENTATION_FORM_RE = re.compile("[\uFB50-\uFDFF\uFE70-\uFEFF]")


def fix_visual_order_arabic(text: str) -> str:
    if not text or not _PRESENTATION_FORM_RE.search(text):
        return text
    fixed_lines = []
    for line in text.split("\n"):
        fixed_lines.append(get_display(unicodedata.normalize("NFKC", line)))
    return "\n".join(fixed_lines)
