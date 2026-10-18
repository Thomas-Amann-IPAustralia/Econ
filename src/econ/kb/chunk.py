"""Stage `chunk`: elements to retrievable chunks, under one of the strategies in config/pipeline.yaml.

Every document has one canonical text: its elements, headings included, joined by blank lines in reading
order. Every chunk records the character ranges of that text it covers (`spans`), its pages and the
boxes of its elements. That shared coordinate system is what lets one test set score every strategy.

- `structure`: chunks never cross a section. Elements are packed in order up to the token budget; a
  paragraph or table too long for one chunk is split at sentence or row boundaries (a table repeats its
  header). A short tail is merged into the previous chunk when it fits. Headings are not repeated in the
  text; they form the chunk's `section` path, which the prefix carries.
- `fixed`: windows of the token budget over the canonical text, with overlap, ignoring structure.

`text` is what a reader and the answer model see. `embed_text` adds the prefix (title, and the section
path for `structure`); only the embedder and keyword index see it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from econ import config
from econ.config import ChunkStrategy, Document
from econ.kb import tokens

SEP = "\n\n"
_SENT = re.compile(r"(?<=[.!?;:])\s+(?=[\"'(\[A-Z0-9•»-])")


@dataclass
class Element:
    seq: int
    label: str
    text: str
    page: int
    boxes: list
    level: int | None
    start: int = 0
    end: int = 0
    cite: bool = False  # set by mark_citations


@dataclass
class Piece:
    """A unit of packing: a whole element or part of one."""

    el: Element
    text: str
    start: int
    end: int


@dataclass
class Chunk:
    pieces: list[Piece] = field(default_factory=list)
    section: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)


def load_elements(doc_id: str) -> list[Element]:
    p = config.path(config.pipeline().paths.library) / "elements" / f"{doc_id}.jsonl"
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    els = [Element(r["seq"], r["label"], r["text"], r["page"], r["boxes"], r.get("level")) for r in rows]
    for e in els:
        if e.label == "table":
            e.text = _compact_table(e.text)
    return place(els)


def place(els: list[Element]) -> list[Element]:
    """Assign each element its range in the canonical text."""
    pos = 0
    for e in els:
        e.start, e.end = pos, pos + len(e.text)
        pos = e.end + len(SEP)
    return els


def canonical_text(els: list[Element]) -> str:
    return SEP.join(e.text for e in els)


def is_heading(e: Element) -> bool:
    return e.label in ("section_header", "title")


def prefix(doc: Document, section: list[str], mode: str) -> str:
    if mode == "none":
        return ""
    if mode == "title" or not section:
        return f"{doc.title}{SEP}"
    return f"{doc.title}\n{' > '.join(section)}{SEP}"


def _compact_table(md: str) -> str:
    # Markdown separator rows and padding cost tokens and carry nothing.
    lines = []
    for line in md.splitlines():
        if re.fullmatch(r"\|?(\s*:?-{3,}:?\s*\|)+\s*:?-*:?\s*\|?", line.strip()):
            line = "|" + "|".join("---" for _ in line.strip().strip("|").split("|")) + "|"
        lines.append(re.sub(r"\s{2,}", " ", line))
    return "\n".join(lines)


def _header_lines(table: str) -> int:
    """Lines of a markdown table that a split repeats: any caption, the column header and its separator."""
    lines = table.split("\n")
    for i, line in enumerate(lines):
        if re.fullmatch(
            r"\|?(\s*:?-{3,}:?\s*\|)+\s*", line.strip() + ("|" if not line.strip().endswith("|") else "")
        ):
            return i + 1
    return 1


def _units(el: Element, budget: int, header: str) -> list[tuple[int, int]]:
    """Character ranges of the element's smallest units: table rows, else sentences; any unit still over
    the budget is cut into runs of words."""
    text = el.text
    if el.label == "table":
        spans, pos = [], 0
        skip = _header_lines(text)
        for i, line in enumerate(text.split("\n")):
            if i >= skip and line.strip():
                spans.append((pos, pos + len(line)))
            pos += len(line) + 1
    else:
        spans, pos = [], 0
        for m in _SENT.finditer(text):
            spans.append((pos, m.start()))
            pos = m.end()
        spans.append((pos, len(text)))
    out = []
    for s, e in spans:
        if s >= e:
            continue
        if tokens.count(_with_header(header, text[s:e])) <= budget:
            out.append((s, e))
            continue
        start = None
        last = s
        for w in re.finditer(r"\S+", text[s:e]):
            ws, we = s + w.start(), s + w.end()
            if start is not None and tokens.count(_with_header(header, text[start:we])) > budget:
                out.append((start, last))
                start = None
            start = ws if start is None else start
            last = we
        if start is not None:
            out.append((start, last))
    return out


def _with_header(header: str, body: str) -> str:
    return f"{header}\n{body}" if header else body


def split_piece(el: Element, budget: int) -> list[Piece]:
    """Split one element into pieces that each fit the budget (in tokens, without prefix). A piece's text
    is a substring of the element's (a table piece also repeats the header), and its span is exact."""
    text = el.text
    header = "\n".join(text.split("\n")[: _header_lines(text)]) if el.label == "table" else ""
    pieces, cur = [], None
    for s, e in _units(el, budget, header):
        if cur is not None and tokens.count(_with_header(header, text[cur[0] : e])) > budget:
            pieces.append(cur)
            cur = None
        cur = (s, e) if cur is None else (cur[0], e)
    if cur is not None:
        pieces.append(cur)
    return [Piece(el, _with_header(header, text[s:e]), el.start + s, el.start + e) for s, e in pieces]


def structure_chunks(doc: Document, els: list[Element], st: ChunkStrategy) -> list[Chunk]:
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    cur: Chunk | None = None

    def section() -> list[str]:
        return [h for _, h in stack]

    def text_of(c: Chunk, extra: Piece | None = None) -> str:
        ps = c.pieces + ([extra] if extra else [])
        return SEP.join(p.text for p in ps)

    def close():
        nonlocal cur
        if cur and cur.pieces:
            chunks.append(cur)
        cur = None

    for e in els:
        if is_heading(e):
            close()
            lvl = e.level or 1
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, e.text.strip()))
            continue
        sec = section()
        budget = st.max_tokens - (tokens.count(prefix(doc, sec, st.prefix)) - 2)
        if cur is None:
            cur = Chunk(section=sec)
        candidate = Piece(e, e.text, e.start, e.end)
        if tokens.count(text_of(cur, candidate)) <= budget:
            cur.pieces.append(candidate)
            continue
        close()
        pieces = split_piece(e, budget) if tokens.count(e.text) > budget else [candidate]
        for p in pieces:
            if cur is None:
                cur = Chunk(section=sec)
            if cur.pieces and tokens.count(text_of(cur, p)) > budget:
                close()
                cur = Chunk(section=sec)
            cur.pieces.append(p)
    close()

    # Merge a short chunk into its predecessor in the same document when the result fits.
    merged: list[Chunk] = []
    for c in chunks:
        body = SEP.join(p.text for p in c.pieces)
        if merged and tokens.count(body) < st.min_tokens:
            prev = merged[-1]
            combined = SEP.join(p.text for p in prev.pieces + c.pieces)
            pfx = prefix(doc, prev.section, st.prefix)
            if tokens.count(pfx + combined) <= st.max_tokens:
                prev.pieces.extend(c.pieces)
                if c.section != prev.section and c.section:
                    prev.headings.append(" > ".join(c.section))
                continue
        merged.append(c)
    return merged


def fixed_chunks(
    doc: Document, kept: list[Element], st: ChunkStrategy, all_els: list[Element] | None = None
) -> list[Chunk]:
    """Windows over the token stream of the kept elements (headings inline), in canonical coordinates."""
    pfx_tokens = tokens.count(prefix(doc, [], st.prefix)) - 2
    # A window can end inside a word; re-tokenising its text may add a token or two, so leave a margin.
    window = st.max_tokens - 2 - pfx_tokens - 4
    step = window - st.overlap_tokens
    stream: list[tuple[int, int, int]] = []
    for k, el in enumerate(kept):
        enc = tokens.reference().encode(el.text, add_special_tokens=False)
        stream.extend((k, el.start + s, el.start + e) for s, e in enc.offsets)
    heads = [el for el in (all_els or kept) if is_heading(el)]
    chunks: list[Chunk] = []
    i = 0
    while i < len(stream):
        seg = stream[i : i + window]
        pieces = []
        for k in dict.fromkeys(t[0] for t in seg):
            el = kept[k]
            ts = [t for t in seg if t[0] == k]
            s, e = ts[0][1], ts[-1][2]
            pieces.append(Piece(el, el.text[s - el.start : e - el.start], s, e))
        before = [h for h in heads if h.start <= pieces[0].start]
        chunks.append(Chunk(pieces=pieces, section=[before[-1].text] if before else []))
        if i + window >= len(stream):
            break
        i += step
    return chunks


def records(doc: Document, chunks: list[Chunk], st: ChunkStrategy) -> list[dict]:
    out = []
    for n, c in enumerate(chunks):
        text = SEP.join(p.text for p in c.pieces)
        section = c.section
        pfx = prefix(doc, section if st.kind == "structure" else [], st.prefix)
        boxes, seen = [], set()
        for p in c.pieces:
            for b in p.el.boxes:
                key = (b["page"], tuple(b["bbox"]))
                if key not in seen:
                    seen.add(key)
                    boxes.append(b)
        spans = []
        for p in c.pieces:
            if spans and p.start <= spans[-1][1] + len(SEP):
                spans[-1][1] = max(spans[-1][1], p.end)
            else:
                spans.append([p.start, p.end])
        out.append(
            {
                "chunk_id": f"{doc.doc_id}:{n:04d}",
                "doc_id": doc.doc_id,
                "seq": n,
                "text": text,
                "embed_text": pfx + text,
                "section": section,
                "headings": c.headings,
                "pages": sorted({b["page"] for b in boxes}),
                "boxes": boxes,
                "spans": spans,
                "elements": [c.pieces[0].el.seq, c.pieces[-1].el.seq],
                "labels": sorted({p.el.label for p in c.pieces}),
                "pieces": len(c.pieces),
                "citation_pieces": sum(p.el.cite for p in c.pieces),
                "tokens": tokens.count(pfx + text),
            }
        )
    return out


# A bibliography entry or a citation-only endnote: "Surname, I. (2020). Title. Journal." or
# "Organisation (2021), Title". Matched on the start of the element plus a publication signal, and only
# for short elements, so a substantive endnote that cites a source keeps its place (D-007).
_CITE_START = re.compile(
    r"""^\s*(\d{1,3}\s*[\x07\s]*)?
    (?:[A-Z][A-Za-z'’\-]+(?:\s[A-Z][A-Za-z'’\-]+)?,\s*(?:[A-Z]\.\s*){1,3}(?:,|&|and|\(|\d)
      |[A-Z][A-Za-z&'’\-\s]{2,60}\s\((19|20)\d{2}[a-z]?\)[,.]?
      |(?:[A-Z][A-Za-z'’\-]+,\s*[A-Z]{1,2},\s*){2}
    )""",
    re.X,
)
_CITE_SIGNAL = re.compile(
    r"(\(?(19|20)\d{2}[a-z]?\)?[.,]|Retrieved|Available (at|from)|https?://|doi|Journal|Working Paper|Press|Review|Report|Accessed)"
)


_REF_HEADING = re.compile(r"\b(references?|bibliography|end ?notes|sources|works cited)\b", re.I)
_BIBLIOGRAPHY = re.compile(r"\b(references|bibliography|works cited)\b", re.I)
_YEAR = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
_PUBLICATION = re.compile(
    r"(Retrieved|Accessed|Available|https?://|www\.|doi|Journal|Review|Press|Working Paper|Discussion Paper"
    r"|Report|Proceedings|Economics|Policy|vol\.|pp\.|\d+\(\d+\)|[A-Z][a-z]+, [A-Z]\.?,|et al)"
)
_MARKER = re.compile(r"((19|20)\d{2}|https?://|www\.|doi|Journal|Working Paper|Press)")


def has_substance(text: str) -> bool:
    """A sentence of 10 or more words with no year, link or publication marker: something an endnote says,
    as opposed to the source it names. Such an element is kept even when it starts with a citation."""
    return any(len(s.split()) >= 10 and not _MARKER.search(s) for s in re.split(r"(?<=[.!?])\s+", text))


def is_citation(e: Element, heading: str = "") -> bool:
    """A bibliography entry or citation-only endnote. Anywhere: a short element that starts like a
    reference and carries a publication signal. Under a References, Bibliography or Endnotes heading,
    also any element with a year and a publication marker (D-008). Never when it says something."""
    if e.label not in ("text", "list_item", "footnote", "reference"):
        return False
    if _BIBLIOGRAPHY.search(heading):
        # A reference list holds nothing but references; long titles would otherwise pass the guard (D-009).
        return bool(_YEAR.search(e.text))
    if has_substance(e.text):
        return False
    if len(e.text) < 600 and _CITE_START.match(e.text) and _CITE_SIGNAL.search(e.text):
        return True
    return bool(_REF_HEADING.search(heading) and _YEAR.search(e.text) and _PUBLICATION.search(e.text))


def mark_citations(els: list[Element]) -> list[Element]:
    heading = ""
    for e in els:
        if is_heading(e):
            heading = e.text
        else:
            e.cite = is_citation(e, heading)
    return els


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def boilerplate(
    docs: dict[str, list[Element]], min_docs: int = 3, min_chars: int = 40, front: int = 4, back: int = 2
) -> set[str]:
    """Front and back matter that recurs nearly verbatim in at least `min_docs` documents: licence terms,
    disclaimers, contact details. They carry no findings and crowd out content (a question about copyright
    retrieved the CC BY notice of every report). A recurring paragraph counts only if every occurrence is
    in the first `front` or last `back` pages of its document: the reports also restate definitions of
    the IP rights in their body text, and those must stay searchable (D-004)."""
    seen: dict[str, set[str]] = {}
    outside: set[str] = set()
    for doc_id, els in docs.items():
        last = max((e.page for e in els), default=0)
        for e in els:
            if is_heading(e) or len(e.text) < min_chars:
                continue
            k = _key(e.text)
            seen.setdefault(k, set()).add(doc_id)
            if front < e.page <= last - back:
                outside.add(k)
    return {k for k, ids in seen.items() if len(ids) >= min_docs and k not in outside}


def chunk_document(
    doc: Document, st: ChunkStrategy, els: list[Element] | None = None, skip: set[str] | None = None
) -> list[dict]:
    """Chunk one document. `skip` holds boilerplate keys; those elements keep their place in the canonical
    text (so gold offsets don't move) but enter no chunk."""
    els = els if els is not None else load_elements(doc.doc_id)
    kept = [e for e in els if not (skip and not is_heading(e) and _key(e.text) in skip)]
    mark_citations(els)
    if st.drop_citations:
        kept = [e for e in kept if not e.cite]
    chunks = structure_chunks(doc, kept, st) if st.kind == "structure" else fixed_chunks(doc, kept, st, els)
    return records(doc, chunks, st)
