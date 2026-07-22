"""Structural extraction of the regjeringen.no register PDFs.

The SMK register (statssekretaerer og politiske raadgivere) is a form
layout: person name in bold 16pt, an affiliation line "(Parti, Fylke)",
then fields whose bold label words sit left of the value column and whose
regular value words sit right of it. Field boundaries are vertical: a new
field opens on a line gap above roughly 20pt, wrap lines sit at 14-16pt.
A row whose value words are bold is the block's printed table header, not
a field. Classification rides font weight, size, x-position and line
gaps only; labels are captured verbatim, never assumed.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pdfplumber

SMK_PARSER_VERSION = "1.0.0"

FOOTER_BAND_PT = 55.0
LINE_TOP_TOLERANCE = 2.5
NAME_MIN_SIZE = 14.0
FIELD_GAP_PT = 20.0
FALLBACK_VALUE_X = 200.0
GENERATED_RE = re.compile(r"generert\s+(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}):(\d{2}))?", re.I)


@dataclass
class Word:
    text: str
    x0: float
    top: float
    page: int
    bold: bool
    size: float


@dataclass
class Field:
    label_words: list[str] = field(default_factory=list)
    value_lines: list[str] = field(default_factory=list)
    order: int = 0
    is_header: bool = False

    @property
    def label(self) -> str:
        return " ".join(self.label_words)

    @property
    def value(self) -> str:
        return "\n".join(self.value_lines)


@dataclass
class SmkPerson:
    name: str
    order: int
    affiliation: str | None = None
    parti: str | None = None
    fylke: str | None = None
    fields: list[Field] = field(default_factory=list)


@dataclass
class SmkParse:
    n_pages: int
    cover_text: str
    generated: str | None
    generated_raw: str | None
    value_x: float
    persons: list[SmkPerson]
    remainder: list[dict]
    parser_version: str = SMK_PARSER_VERSION


def _lines(pdf: pdfplumber.PDF) -> list[list[Word]]:
    out: list[list[Word]] = []
    for i, page in enumerate(pdf.pages):
        cutoff = page.height - FOOTER_BAND_PT
        words = [
            Word(w["text"], w["x0"], w["top"], i, "Bold" in w["fontname"], w["size"])
            for w in page.extract_words(extra_attrs=["fontname", "size"])
            if w["top"] < cutoff
        ]
        words.sort(key=lambda w: (w.top, w.x0))
        cur: list[Word] = []
        cur_top: float | None = None
        for w in words:
            if cur_top is None or abs(w.top - cur_top) <= LINE_TOP_TOLERANCE:
                cur.append(w)
                cur_top = w.top if cur_top is None else cur_top
            else:
                out.append(sorted(cur, key=lambda x: x.x0))
                cur, cur_top = [w], w.top
        if cur:
            out.append(sorted(cur, key=lambda x: x.x0))
    return out


def _value_x(lines: list[list[Word]]) -> float:
    xs = Counter(
        round(w.x0, 1)
        for line in lines
        for w in line
        if not w.bold and w.size < 12.0 and 150.0 < w.x0 < 400.0
    )
    if not xs:
        return FALLBACK_VALUE_X
    return xs.most_common(1)[0][0] - 4.0


def parse_smk(pdf_path: str) -> SmkParse:
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        lines = _lines(pdf)
    cover_lines = [ln for ln in lines if ln[0].page == 0]
    body = [ln for ln in lines if ln[0].page >= 1]
    cover_text = "\n".join(" ".join(w.text for w in ln) for ln in cover_lines)
    m = GENERATED_RE.search(cover_text)
    generated = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
    vx = _value_x(body)

    persons: list[SmkPerson] = []
    remainder: list[dict] = []
    person: SmkPerson | None = None
    fld: Field | None = None
    prev_top: float | None = None
    prev_page: int | None = None

    for ln in body:
        text = " ".join(w.text for w in ln)
        top, page = ln[0].top, ln[0].page
        gap = None if prev_page != page else top - (prev_top or top)
        prev_top, prev_page = top, page

        if all(w.bold for w in ln) and ln[0].size >= NAME_MIN_SIZE:
            person = SmkPerson(name=text, order=len(persons) + 1)
            persons.append(person)
            fld = None
            continue
        if person is None:
            remainder.append({"page": page, "top": round(top, 1), "text": text})
            continue

        left = [w for w in ln if w.x0 < vx]
        right = [w for w in ln if w.x0 >= vx]

        if (
            person.affiliation is None
            and not person.fields
            and left
            and not right
            and not any(w.bold for w in left)
            and text.startswith("(")
        ):
            person.affiliation = text
            inside = text.strip("()")
            if "," in inside:
                parti, fylke = inside.split(",", 1)
                person.parti, person.fylke = parti.strip(), fylke.strip()
            else:
                person.parti = inside.strip() or None
            continue

        left_bold = bool(left) and all(w.bold for w in left)
        new_field = left_bold and (gap is None or gap > FIELD_GAP_PT or fld is None)

        if new_field:
            fld = Field(order=len(person.fields) + 1)
            fld.label_words = [w.text for w in left]
            fld.is_header = bool(right) and all(w.bold for w in right)
            person.fields.append(fld)
            if right and not fld.is_header:
                fld.value_lines.append(" ".join(w.text for w in right))
            elif fld.is_header:
                fld.value_lines.append(" ".join(w.text for w in right))
            continue

        if fld is not None:
            if left_bold:
                fld.label_words.extend(w.text for w in left)
            elif left:
                remainder.append({"page": page, "top": round(top, 1), "text": text})
                continue
            if right:
                fld.value_lines.append(" ".join(w.text for w in right))
            continue

        remainder.append({"page": page, "top": round(top, 1), "text": text})

    return SmkParse(
        n_pages=n_pages,
        cover_text=cover_text,
        generated=generated,
        generated_raw=m.group(0) if m else None,
        value_x=vx,
        persons=persons,
        remainder=remainder,
    )
