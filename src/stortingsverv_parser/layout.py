"""Coordinate-based structural extraction of register PDFs.

The register is a two-column Word document: person headers in bold at the
left margin, paragraph markers and their labels in a left column, entry
content in a right column. Linear text extraction destroys the pairing
between markers and content whenever short sections stack, so every
classification here rides layout structure: font weight, font size and
x-position. No literal label text is ever matched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pdfplumber

PARSER_VERSION = "1.0.0"

FOOTER_BAND_PT = 65.0
LINE_TOP_TOLERANCE = 2.5
HEADING_MIN_SIZE = 13.0
BODY_MIN_SIZE = 10.5
LEFT_MARGIN_MAX_X0 = 110.0
FALLBACK_COLUMN_SPLIT = 205.0


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    page: int
    bold: bool
    size: float


@dataclass
class Line:
    words: list[Word]

    @property
    def page(self) -> int:
        return self.words[0].page

    @property
    def top(self) -> float:
        return self.words[0].top

    @property
    def x0(self) -> float:
        return self.words[0].x0

    @property
    def bold(self) -> bool:
        return all(w.bold for w in self.words)

    @property
    def size(self) -> float:
        return max(w.size for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def split_columns(self, threshold: float) -> tuple[list[Word], list[Word]]:
        left = [w for w in self.words if w.x0 < threshold]
        right = [w for w in self.words if w.x0 >= threshold]
        return left, right


@dataclass
class Section:
    marker: str
    label_words: list[str] = field(default_factory=list)
    content_lines: list[str] = field(default_factory=list)
    order: int = 0

    @property
    def label(self) -> str:
        return " ".join(self.label_words)

    @property
    def text(self) -> str:
        return "\n".join(self.content_lines)


@dataclass
class Table:
    marker: str
    header_cells: list[str]
    header_spans: list[tuple[float, float]]
    rows: list[list[str]] = field(default_factory=list)


CELL_GAP_PT = 8.0
TABLE_MAX_SIZE = 10.4


def _group_cells(words: list[Word]) -> list[tuple[str, float, float]]:
    cells: list[tuple[str, float, float]] = []
    buf: list[Word] = []
    for w in words:
        if buf and (w.x0 - buf[-1].x1) > CELL_GAP_PT:
            cells.append((" ".join(b.text for b in buf), buf[0].x0, buf[-1].x1))
            buf = []
        buf.append(w)
    if buf:
        cells.append((" ".join(b.text for b in buf), buf[0].x0, buf[-1].x1))
    return cells


def _map_row(table: Table, cells: list[tuple[str, float, float]]) -> list[str]:
    row = [""] * len(table.header_cells)
    extra: list[str] = []
    for text, x0, x1 in cells:
        best, best_ov = None, 0.0
        for j, (hx0, hx1) in enumerate(table.header_spans):
            ov = min(x1, hx1 + CELL_GAP_PT) - max(x0, hx0 - CELL_GAP_PT)
            if ov > best_ov:
                best, best_ov = j, ov
        if best is None:
            dists = [abs(x0 - hx0) for hx0, _ in table.header_spans]
            best = dists.index(min(dists))
        if row[best]:
            row[best] += " " + text
        else:
            row[best] = text
    if extra:
        row.append(" | ".join(extra))
    return row


@dataclass
class Person:
    header: str
    section_heading: str
    order: int
    sections: list[Section] = field(default_factory=list)
    note_lines: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)

    @property
    def note(self) -> str:
        return "\n".join(self.note_lines)


@dataclass
class DocumentParse:
    n_pages: int
    cover_text: str
    preamble_text: str
    column_split: float
    persons: list[Person]
    remainder: list[dict]
    parser_version: str = PARSER_VERSION


def _extract_words(pdf: pdfplumber.PDF) -> list[Word]:
    out: list[Word] = []
    for i, page in enumerate(pdf.pages):
        cutoff = page.height - FOOTER_BAND_PT
        for w in page.extract_words(extra_attrs=["fontname", "size"]):
            if w["top"] >= cutoff:
                continue
            out.append(
                Word(
                    text=w["text"],
                    x0=w["x0"],
                    x1=w["x1"],
                    top=w["top"],
                    page=i,
                    bold="Bold" in w["fontname"],
                    size=w["size"],
                )
            )
    return out


def _group_lines(words: list[Word]) -> list[Line]:
    lines: list[Line] = []
    for page in sorted({w.page for w in words}):
        page_words = sorted(
            (w for w in words if w.page == page), key=lambda w: (w.top, w.x0)
        )
        current: list[Word] = []
        current_top: float | None = None
        for w in page_words:
            if current_top is None or abs(w.top - current_top) <= LINE_TOP_TOLERANCE:
                current.append(w)
                current_top = w.top if current_top is None else current_top
            else:
                lines.append(Line(sorted(current, key=lambda x: x.x0)))
                current = [w]
                current_top = w.top
        if current:
            lines.append(Line(sorted(current, key=lambda x: x.x0)))
    return lines


def _column_split(lines: list[Line]) -> float:
    from collections import Counter

    starts = Counter(
        round(line.x0, 1)
        for line in lines
        if not line.bold and line.size >= BODY_MIN_SIZE and 150.0 < line.x0 < 400.0
    )
    if not starts:
        return FALLBACK_COLUMN_SPLIT
    modal_x0, _ = starts.most_common(1)[0]
    return modal_x0 - 6.0


def _is_marker_start(left: list[Word]) -> bool:
    return bool(left) and left[0].text.startswith("§")


def _consume_marker(left: list[Word]) -> tuple[str, list[str]]:
    if left[0].text == "§" and len(left) > 1:
        return "§" + left[1].text, [w.text for w in left[2:]]
    return left[0].text, [w.text for w in left[1:]]


def parse_document(pdf_path: str) -> DocumentParse:
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        words = _extract_words(pdf)
    lines = _group_lines(words)
    threshold = _column_split(lines)

    cover_lines: list[str] = []
    preamble_lines: list[str] = []
    persons: list[Person] = []
    remainder: list[dict] = []

    heading: str | None = None
    person: Person | None = None
    section: Section | None = None
    header_open = False
    order = 0

    def close_header() -> None:
        nonlocal header_open
        header_open = False

    for idx, line in enumerate(lines):
        nxt = lines[idx + 1] if idx + 1 < len(lines) else None
        if (
            line.page >= 1
            and line.size >= HEADING_MIN_SIZE
            and line.x0 <= LEFT_MARGIN_MAX_X0
            and len(line.words) <= 2
            and nxt is not None
            and nxt.bold
            and nxt.size >= BODY_MIN_SIZE
            and nxt.x0 <= LEFT_MARGIN_MAX_X0
        ):
            heading = line.text
            person = None
            section = None
            close_header()
            continue

        if heading is None:
            if line.page == 0:
                cover_lines.append(line.text)
            else:
                preamble_lines.append(line.text)
            continue

        if line.size <= TABLE_MAX_SIZE and person is not None:
            cells = _group_cells(line.words)
            if line.bold:
                table = Table(
                    marker=section.marker if section else "",
                    header_cells=[c[0] for c in cells],
                    header_spans=[(c[1], c[2]) for c in cells],
                )
                person.tables.append(table)
            elif person.tables:
                person.tables[-1].rows.append(_map_row(person.tables[-1], cells))
            else:
                remainder.append(
                    {"page": line.page, "top": round(line.top, 1), "text": line.text}
                )
            continue

        if line.bold and line.x0 <= LEFT_MARGIN_MAX_X0 and line.size >= BODY_MIN_SIZE:
            if header_open and person is not None and ")" not in person.header:
                person.header += " " + line.text
            else:
                order += 1
                person = Person(header=line.text, section_heading=heading, order=order)
                persons.append(person)
                section = None
                header_open = True
            if person is not None and ")" in person.header:
                close_header()
            continue

        close_header()

        if person is None:
            remainder.append({"page": line.page, "top": round(line.top, 1), "text": line.text})
            continue

        left, right = line.split_columns(threshold)

        if left and _is_marker_start(left):
            marker, label_words = _consume_marker(left)
            section = Section(marker=marker, label_words=label_words, order=len(person.sections) + 1)
            person.sections.append(section)
            if right:
                section.content_lines.append(" ".join(w.text for w in right))
            continue

        if left and section is not None and not section.content_lines and not right:
            section.label_words.extend(w.text for w in left)
            continue

        if section is None:
            person.note_lines.append(line.text)
            continue

        if right and not left and section is not None:
            section.content_lines.append(" ".join(w.text for w in right))
            continue

        if section is not None:
            section.content_lines.append(line.text)
            continue

        remainder.append({"page": line.page, "top": round(line.top, 1), "text": line.text})

    return DocumentParse(
        n_pages=n_pages,
        cover_text="\n".join(cover_lines),
        preamble_text="\n".join(preamble_lines),
        column_split=threshold,
        persons=persons,
        remainder=remainder,
    )
