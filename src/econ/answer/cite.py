"""Citations by sentence (answer-v5 onwards, D-026): code writes the quotes, not the model.

Each evidence passage is shown to the answer model split into numbered sentences, `[3.2]` being passage 3's
second sentence. The model cites those ids in its prose and writes no claims or quotes. `build` then turns
each group of ids into a claim whose quotes are the cited sentences, copied from the passage's own text, and
rewrites the group as the claim's marker `[k]`, so the check, the trail, the highlights and the page links
work as before. Quotes are exact by construction; an id that was not shown is an error the check reports.

Sentences are split deterministically: at line breaks, and after . ! or ? followed by a space and a capital,
digit or opening bracket, except after common abbreviations and initials.
"""

from __future__ import annotations

import re

from econ.answer.schema import AnswerV3, Citation, Claim

_ABBREV = {
    "e.g", "i.e", "etc", "vs", "cf", "al", "no", "nos", "fig", "figs", "approx", "dr", "mr", "mrs", "ms",
    "prof", "st", "inc", "ltd", "pty", "co", "corp", "dept", "govt", "jan", "feb", "mar", "apr", "jun", "jul",
    "aug", "sep", "sept", "oct", "nov", "dec", "u.s", "u.k", "p", "pp", "vol", "ch", "sec", "est", "ed", "eds",
}  # fmt: skip
_END = re.compile(r"[.!?][\"'”’)\]]*(?=\s+[\"'“‘(\[]?[A-Z0-9])")
IDS = re.compile(r"\[(\d{1,3})\.(\d{1,3})\]")
GROUP = re.compile(r"(?:\[\d{1,3}\.\d{1,3}\][ \t]?)+")
_BARE = re.compile(r"\[(\d{1,3})\](?!\.\d)")
_RULE = re.compile(r"[\s|:\-]+")


def sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence in `text`, in order, without surrounding whitespace."""
    cuts: list[tuple[int, int]] = []
    for line in re.finditer(r"[^\n]+", text):
        s, start = line.group(), 0
        for m in _END.finditer(s):
            word = re.search(r"(\S+)$", s[start : m.start()])
            w = word.group(1).lower().rstrip(".") if word else ""
            if w in _ABBREV or re.fullmatch(r"[a-z]", w):
                continue  # an abbreviation or an initial, not the end of a sentence
            cuts.append((line.start() + start, line.start() + m.end()))
            start = m.end()
        cuts.append((line.start() + start, line.end()))
    out = []
    for a, b in cuts:
        piece = text[a:b]
        if piece.strip() and not _RULE.fullmatch(piece.strip()):  # a table's rule line is not a sentence
            lead = len(piece) - len(piece.lstrip())
            out.append((a + lead, a + lead + len(piece.strip())))
    return out


def numbered(n: int, text: str, wrap) -> tuple[str, dict[int, str]]:
    """The passage's text with `[n.k]` before each sentence (the text itself passed through `wrap`, the
    prompt's defang), and sentence number -> sentence text."""
    parts, table, prev = [], {}, 0
    for k, (a, b) in enumerate(sentences(text), start=1):
        parts.append(wrap(text[prev:a]))
        parts.append(f"[{n}.{k}] " + wrap(text[a:b]))
        table[k] = text[a:b]
        prev = b
    parts.append(wrap(text[prev:]))
    return "".join(parts), table


def _claim_text(segment: str) -> str:
    """The prose a group of ids backs, without markdown: everything since the previous group of ids or the
    start of the line, whichever is later. A group at the end of a paragraph backs the whole paragraph, so
    the label is every sentence of it, not just the last."""
    seg = re.sub(r"[*_`#>]+", "", segment.rsplit("\n", 1)[-1])
    pieces = [p.strip(" -•:;") for p in re.split(r"(?<=[.!?])\s+", seg)]
    return " ".join(p for p in pieces if re.search(r"\w", p))


def build(prose_answer, table: dict[tuple[int, int], str]) -> tuple[AnswerV3, list[str]]:
    """The answer with claims made from its sentence ids, and the errors in those ids. `table` maps
    (passage, sentence) to the sentence's text, for the passages the model was shown."""
    prose = prose_answer.answer
    errors: list[str] = []
    bare = sorted({int(m) for m in _BARE.findall(prose)})
    if bare:
        errors.append(
            f"the prose uses markers like [{bare[0]}]; cite sentences by their ids, such as [{bare[0]}.1]"
        )
    claims: list[Claim] = []
    number: dict[tuple, int] = {}
    out, pos = [], 0
    for g in GROUP.finditer(prose):
        ids = list(dict.fromkeys((int(a), int(b)) for a, b in IDS.findall(g.group())))
        for i in ids:
            if i not in table:
                errors.append(f"the prose cites sentence [{i[0]}.{i[1]}], which was not shown")
        known = tuple(i for i in ids if i in table)
        out.append(prose[pos : g.start()])
        if known:
            if known not in number:
                text = _claim_text(prose[pos : g.start()]) or "See the cited sentences."
                cits = [Citation(evidence=n, quote=table[(n, s)]) for n, s in known]
                claims.append(Claim(text=text, citations=cits))
                number[known] = len(claims)
            trail = g.group()[len(g.group().rstrip()) :]
            out.append(f"[{number[known]}]{trail}")
        pos = g.end()
    out.append(prose[pos:])
    built = AnswerV3(
        coverage=prose_answer.coverage,
        answer="".join(out),
        claims=claims,
        gaps=prose_answer.gaps,
        follow_ups=prose_answer.follow_ups,
    )
    return built, errors
