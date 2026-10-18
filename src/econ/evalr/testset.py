"""The retrieval test set: needs with verbatim gold spans, located in each document's canonical text.

A need is a question plus one or more gold items, each a verbatim passage that answers it (or part of it).
A gold item may list alternatives (`alt`): the same finding stated elsewhere, such as an executive summary
and a conclusion, or two years' reports. Covering any alternative covers the item. Gold is located by
text, not by chunk, so one set scores every chunking strategy: a chunk is relevant to a gold when its
spans cover at least `cover` of the gold's characters.

The split is fixed by a hash of the need id: dev to choose, test to report.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from econ import config
from econ.kb.chunk import canonical_text, load_elements
from econ.manifest import StageError
from econ.textcheck import normalise

KINDS = ("lookup", "explain", "paraphrase", "multi", "trend")


@dataclass(frozen=True)
class Gold:
    doc_id: str
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class Need:
    id: str
    kind: str
    question: str
    golds: tuple[tuple[Gold, ...], ...]  # each item: its alternatives
    split: str


def split_of(need_id: str) -> str:
    return "dev" if int(hashlib.sha256(need_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Normalised text and, for each of its characters, the index of the original character."""
    out, idx = [], []
    prev_space = True
    for i, ch in enumerate(text):
        n = normalise(ch) if not ch.isspace() else " "
        if n == "":
            continue
        if n == " ":
            if prev_space:
                continue
            prev_space = True
        else:
            prev_space = False
        for c in n:
            out.append(c)
            idx.append(i)
    return "".join(out), idx


_cache: dict[str, tuple[str, list[int]]] = {}


def _norm_doc(doc_id: str) -> tuple[str, list[int]]:
    if doc_id not in _cache:
        _cache[doc_id] = _norm_map(canonical_text(load_elements(doc_id)))
    return _cache[doc_id]


def locate(doc_id: str, quote: str, *, everywhere: bool = True) -> list[Gold]:
    """Every verbatim occurrence of the quote: in its own document (at least one, or the set is invalid)
    and, with `everywhere`, in any other document. Repeated text (a finding restated in a box, a figure
    note printed under several figures, a sentence reused in a later report) is equally a correct find."""
    q = re.sub(r"\s+", " ", normalise(quote)).strip()
    docs = sorted(config.sources().by_id()) if everywhere else [doc_id]
    out = []
    for d in [doc_id, *[x for x in docs if x != doc_id]]:
        norm, idx = _norm_doc(d)
        i = norm.find(q)
        while i >= 0:
            out.append(Gold(d, idx[i], idx[i + len(q) - 1] + 1, quote))
            i = norm.find(q, i + 1)
        if d == doc_id and not out:
            raise StageError("gold quote not found in its document's text", item=f"{doc_id}: {quote[:60]!r}")
    return out


def load(path: Path | None = None) -> list[Need]:
    path = path or config.path("eval/testset/silver-v1.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    known = set(config.sources().by_id())
    needs, seen = [], set()
    for n in data["needs"]:
        if n["id"] in seen:
            raise StageError("duplicate need id", item=n["id"])
        seen.add(n["id"])
        if n["kind"] not in KINDS:
            raise StageError(f"unknown kind {n['kind']!r}", item=n["id"])
        golds = []
        for g in n["gold"]:
            alts = []
            for a in [g, *g.get("alt", [])]:
                if a["doc_id"] not in known:
                    raise StageError(f"unknown doc_id {a['doc_id']!r}", item=n["id"])
                if len(a["quote"].split()) < 8:
                    raise StageError("gold quote shorter than 8 words", item=n["id"])
                alts.extend(g2 for g2 in locate(a["doc_id"], a["quote"]) if g2 not in alts)
            golds.append(tuple(alts))
        needs.append(Need(n["id"], n["kind"], n["question"].strip(), tuple(golds), split_of(n["id"])))
    return needs
