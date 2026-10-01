"""Read the text of a clause PDF, one string per page, in reading order.

Many clause documents are set in two columns. Reading a page row by row would
interleave the columns, so a page whose words leave a clear vertical gutter
near the middle is read left column first, then right column. Lines that cross
the gutter, such as a centred title, split the page into bands that are read
one after another. Lines above or below the column body, such as page numbers
and running footers, stay at the top or bottom of the page text, where the
splitter removes them.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber

# Two words on the same line are separated when the gap between their
# characters exceeds this many points.
_X_TOLERANCE = 3
# Words whose tops differ by at most this many points are on the same line.
_Y_TOLERANCE = 3
# The gutter of a two-column page is searched for in this band of the page
# width. Each side must hold some words, and few words may cross it.
_GUTTER_SEARCH = (0.35, 0.65)
_MIN_WORDS_BESIDE_GUTTER = 8
_MAX_WORDS_ACROSS_GUTTER = 0.15
# A line at least this share of the page width, and mostly covered by its
# words, is body text rather than a table row or a spread-out footer.
_WIDE_LINE = 0.3
_DENSE_LINE = 0.8
# A two-column page has at least this many body lines in its columns.
_MIN_BODY_LINES = 5
# A column line may be indented from its column's left edge by up to this
# share of the page width.
_INDENT = 0.25


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    x1: float
    top: float


def read_pages(path: str | Path) -> list[str]:
    """Return the text of every page of the PDF at `path`, in reading order."""
    with pdfplumber.open(path) as pdf:
        return [_page_text(page) for page in pdf.pages]


def _page_text(page: Any) -> str:
    page = _without_duplicate_chars(page)
    words = [
        _Word(w["text"], w["x0"], w["x1"], w["top"])
        for w in page.extract_words(x_tolerance=_X_TOLERANCE, y_tolerance=_Y_TOLERANCE)
    ]
    width = float(page.width)
    gutter = _find_gutter(words, width)
    if gutter is None:
        return _text(_rows(words))

    left, right = (_rows(column) for column in _split_at(gutter, words))
    if sum(1 for row in left + right if _is_body_line(row, width)) < _MIN_BODY_LINES:
        # A gap between table cells is not a gutter: body text fills a column.
        return _text(_rows(words))

    # The column body runs from the first to the last line that starts at its
    # column's left edge, allowing for indented items. Page numbers and running
    # footers are centred or right-aligned, so they fall outside it.
    in_column = [row for column in (left, right) for row in _column_lines(column, width)]
    body_top = min(row[0].top for row in in_column) - _Y_TOLERANCE
    body_bottom = max(row[0].top for row in in_column) + _Y_TOLERANCE
    rows = _rows(w for w in words if w.top < body_top)
    band: list[_Word] = []
    for row in _rows(w for w in words if body_top <= w.top <= body_bottom):
        if any(w.x0 < gutter < w.x1 for w in row):
            rows += _read_band(band, gutter) + [row]
            band = []
        else:
            band += row
    rows += _read_band(band, gutter)
    rows += _rows(w for w in words if w.top > body_bottom)
    return _text(rows)


def _without_duplicate_chars(page: Any) -> Any:
    """Drop characters drawn twice at the same place, as some PDFs do for bold.

    Matches pdfplumber's dedupe_chars (same text, font and size, at most one
    point apart), which sorts every character and dominates the reading time
    of a dense page. This version looks only at nearby grid cells.
    """
    seen: dict[tuple[str, str, float, int, int], list[tuple[float, float]]] = {}
    duplicates: set[int] = set()
    for char in page.chars:
        x, y = char["x0"], char["top"]
        kind = (char["text"], char["fontname"], char["size"])
        cell = (round(x), round(y))
        near = (
            seen.get((*kind, cell[0] + dx, cell[1] + dy), [])
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        )
        if any(abs(x - x2) <= 1 and abs(y - y2) <= 1 for found in near for x2, y2 in found):
            duplicates.add(id(char))
        else:
            seen.setdefault((*kind, *cell), []).append((x, y))
    if not duplicates:
        return page
    return page.filter(lambda obj: id(obj) not in duplicates)


def _find_gutter(words: list[_Word], width: float) -> int | None:
    """Return an x position that splits the page into two columns, if there is one."""
    best: tuple[int, float, int] | None = None
    start, end = (int(width * share) for share in _GUTTER_SEARCH)
    for x in range(start, end):
        left = sum(1 for w in words if w.x1 <= x)
        right = sum(1 for w in words if w.x0 >= x)
        if min(left, right) < _MIN_WORDS_BESIDE_GUTTER:
            continue
        # Prefer the fewest words crossing x, then the position nearest the middle.
        candidate = (len(words) - left - right, abs(x - width / 2), x)
        if best is None or candidate < best:
            best = candidate
    if best is None or best[0] > _MAX_WORDS_ACROSS_GUTTER * len(words):
        return None
    return best[2]


def _is_body_line(row: list[_Word], width: float) -> bool:
    extent = max(w.x1 for w in row) - row[0].x0
    covered = sum(w.x1 - w.x0 for w in row)
    return extent > width * _WIDE_LINE and covered >= extent * _DENSE_LINE


def _column_lines(column: list[list[_Word]], width: float) -> list[list[_Word]]:
    """The rows of a column that start at its left edge, or indented from it."""
    body = [row for row in column if _is_body_line(row, width)] or column
    edge = min(row[0].x0 for row in body)
    return [row for row in column if edge - _X_TOLERANCE <= row[0].x0 <= edge + width * _INDENT]


def _read_band(words: list[_Word], gutter: int) -> list[list[_Word]]:
    """Rows of the left column, then rows of the right column."""
    left, right = _split_at(gutter, words)
    return _rows(left) + _rows(right)


def _split_at(gutter: int, words: list[_Word]) -> tuple[list[_Word], list[_Word]]:
    """The words left of the gutter and the words right of it; words across it are in neither."""
    return [w for w in words if w.x1 <= gutter], [w for w in words if w.x0 >= gutter]


def _rows(words: Iterable[_Word]) -> list[list[_Word]]:
    """Group words into lines, top to bottom, each line ordered left to right."""
    rows: list[list[_Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and abs(word.top - rows[-1][0].top) <= _Y_TOLERANCE:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w.x0)
    return rows


def _text(rows: list[list[_Word]]) -> str:
    return "\n".join(" ".join(w.text for w in row) for row in rows)
