"""The evidence atlas as a second knowledge base (D-038): ingest its passages, write their context notes, and turn
them into chunks in Econ's shape for `econ index --kb atlas`.

The atlas writes its own passages (Aus-GII-Breakdown, `analysis/atlas/passages.mjs`): every page split into
passages of at most 260 words, one JSON line each, with a metadata file holding their sha256. That file is the
contract. `econ atlas-ingest` reads it at a named commit (from raw.githubusercontent.com) or from a local checkout,
and refuses it unless:
- its sha256 matches the metadata, and the writer's version is the one configured;
- every line passes a strict model (unknown keys are errors) and every id is unique and in order;
- no passage exceeds the word cap or, by the reference tokenizer, the token cap;
- no passage has a high-severity text-check finding (the sweep's rule: Claude never edits config/allowlist.yaml;
  a finding is proposed to the owner).

It writes `library/atlas/passages.jsonl` (the bytes as received), `library/atlas/source.json` (the commit, the
hashes and the counts) and `library/atlas/notes.jsonl` (atlas-notes-v1: one note a passage, written by code, no
model; search only, never evidence, hidden from every API view, as D-013's notes are).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from econ import config, textcheck
from econ.manifest import Run, StageError, write_json_atomic, write_text_atomic

KINDS = ("observation", "glossary", "lens", "question", "source", "page")
STAGE_NAME = {"1": "each variable on its own", "2": "pairs of variables", "3": "many variables together"}
OBS_ID = re.compile(r"^[UBM]\d{1,3}$")


class Passage(BaseModel):
    """One line of the atlas's passages file (atlas-passages-v1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id: str = Field(pattern=r"^atlas-[A-Za-z0-9_-]+:\d{4}$")
    doc_id: str = Field(pattern=r"^atlas-[A-Za-z0-9_-]+$")
    kind: Literal["observation", "glossary", "lens", "question", "source", "page"]
    observation: str | None = Field(None, pattern=r"^[UBM]\d{1,3}$")
    stage: Literal["1", "2", "3"] | None = None
    lens: str | None = None
    lens_name: str | None = None
    strength: Literal["descriptive", "observational", "causal", "projected"] | None = None
    chapter: str | None = None
    title: str = Field(min_length=1)
    section: list[str]
    url: str = Field(pattern=r"^https://[^\s]+#/[^\s]*$")
    related: list[str]
    text: str = Field(min_length=1)


# --- reading -------------------------------------------------------------------------------------------------


def _git_head(repo: Path) -> tuple[str | None, bool]:
    try:
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "evidence/data"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, False
    return head.stdout.strip(), bool(status.stdout.strip())


def read_source(from_path: str | None = None, ref: str | None = None) -> tuple[bytes, bytes, dict]:
    """The passages file and its metadata, and where they came from: a local checkout (`from_path`, the
    checkout's root or the passages file) or the repository at commit `ref` on raw.githubusercontent.com."""
    src = config.atlas().source
    if from_path is not None:
        p = Path(from_path)
        root = p if p.is_dir() else p.parents[2]
        jsonl, meta = root / src.path, root / src.meta_path
        if not jsonl.exists() or not meta.exists():
            raise StageError(f"no passages file at {jsonl}", item=str(jsonl))
        head, dirty = _git_head(root)
        return jsonl.read_bytes(), meta.read_bytes(), {"from": "checkout", "ref": head, "dirty": dirty}
    import httpx

    ref = ref or src.ref
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise StageError("--ref must be a full 40-character commit sha", item=ref)
    base = f"https://raw.githubusercontent.com/{src.repo}/{ref}"
    out = []
    for rel in (src.path, src.meta_path):
        try:
            r = httpx.get(f"{base}/{rel}", timeout=60, follow_redirects=True)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise StageError(f"could not fetch {rel} at {ref[:12]}: {type(e).__name__}", item=rel) from e
        out.append(r.content)
    return out[0], out[1], {"from": "github", "ref": ref, "dirty": False}


# --- checking ------------------------------------------------------------------------------------------------


def words(text: str) -> int:
    return len(text.split())


def validate(jsonl: bytes, meta_bytes: bytes, *, count_tokens=None) -> tuple[list[Passage], dict]:
    """The passages, checked; raises StageError with the first failing passage's id."""
    cfg = config.atlas()
    meta = json.loads(meta_bytes)
    if meta.get("version") != cfg.passages_version:
        raise StageError(f"passages are {meta.get('version')!r}; this ingest reads {cfg.passages_version!r}")
    sha = hashlib.sha256(jsonl).hexdigest()
    if sha != meta.get("passages_sha256"):
        raise StageError(
            f"passages.jsonl's sha256 {sha[:12]} is not the metadata's {str(meta.get('passages_sha256'))[:12]}"
        )
    passages: list[Passage] = []
    for i, line in enumerate(jsonl.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            passages.append(Passage.model_validate_json(line))
        except ValidationError as e:
            raise StageError(
                f"line {i} is not a valid passage: {str(e).splitlines()[0]}", item=f"line {i}"
            ) from e
    if len(passages) != meta.get("passages"):
        raise StageError(f"{len(passages)} passages, but the metadata says {meta.get('passages')}")
    seen: set[str] = set()
    expect: dict[str, int] = {}
    if count_tokens is None:
        from econ.kb import tokens

        count_tokens = tokens.count
    for p in passages:
        if p.passage_id in seen:
            raise StageError("duplicate passage id", item=p.passage_id)
        seen.add(p.passage_id)
        doc, seq = p.passage_id.rsplit(":", 1)
        if doc != p.doc_id or int(seq) != expect.get(doc, 0):
            raise StageError("passage ids must run 0000, 0001, ... within their document", item=p.passage_id)
        expect[doc] = int(seq) + 1
        if p.kind == "observation" and not (p.observation and p.stage and p.strength and p.lens):
            raise StageError(
                "an observation passage needs its id, stage, strength and lens", item=p.passage_id
            )
        if words(p.text) > cfg.word_cap:
            raise StageError(f"{words(p.text)} words, over the cap of {cfg.word_cap}", item=p.passage_id)
        n = count_tokens(p.text)
        if n > cfg.max_tokens:
            raise StageError(f"{n} tokens, over the cap of {cfg.max_tokens}", item=p.passage_id)
        for field in (p.text, p.title, *p.section, p.chapter or ""):
            found = textcheck.high(textcheck.scan(field))
            if found:
                raise StageError(
                    f"high-severity text-check finding ({found[0].rule}): propose an allowlist entry to the owner",
                    item=p.passage_id,
                )
    return passages, meta


# --- notes and chunks ----------------------------------------------------------------------------------------


def headline(p: Passage) -> str:
    return p.title.split(": ", 1)[1] if p.kind == "observation" and ": " in p.title else p.title


def note(p: Passage) -> str:
    """atlas-notes-v1: where the passage sits, in words a question might use. Deterministic, free."""
    sec = " > ".join(p.section)
    if p.kind == "observation":
        return (
            f"Evidence atlas, Stage {p.stage} ({STAGE_NAME[p.stage]}), observation {p.observation} on the "
            f"{p.lens_name} lens, section {p.chapter}; {p.strength}. Headline: {headline(p)}. Part: {sec}."
        )
    what = {
        "glossary": "glossary term",
        "lens": "lens page",
        "question": "research question",
        "source": "data source",
        "page": "page",
    }[p.kind]
    return f"Evidence atlas, {what}: {p.title}. Part: {sec}."


def to_chunk(p: Passage, seq: int, n_tokens: int, context_note: str) -> dict:
    """A passage in the shape Index and the pipeline read: no pages or boxes (a passage leads to its atlas page,
    `url`), and the atlas's own fields beside Econ's."""
    return {
        "chunk_id": p.passage_id,
        "doc_id": p.doc_id,
        "seq": seq,
        "text": p.text,
        "embed_text": p.text,
        "context_note": context_note,
        "section": list(p.section),
        "headings": [],
        "pages": [],
        "boxes": [],
        "spans": [[0, len(p.text)]],
        "tokens": n_tokens,
        "kind": p.kind,
        "observation": p.observation,
        "stage": p.stage,
        "lens": p.lens,
        "lens_name": p.lens_name,
        "strength": p.strength,
        "chapter": p.chapter,
        "title": p.title,
        "url": p.url,
        "related": list(p.related),
    }


def doc_entry(doc_id: str, ps: list[Passage], year: int) -> dict:
    """The catalogue entry for one atlas page: Econ's fields (so the pipeline's views work) and the atlas's."""
    cfg = config.atlas()
    first = ps[0]
    return {
        "doc_id": doc_id,
        "title": first.title,
        "year": year,
        "series": cfg.series,
        "authors": [],
        "url": first.url,
        "note": None,
        "publisher": cfg.publisher,
        "licence": cfg.licence,
        "page_count": 0,
        "pages": {},
        "ocr": False,
        "chunks": len(ps),
        "kind": first.kind,
        "observation": first.observation,
        "stage": first.stage,
        "lens": first.lens,
        "lens_name": first.lens_name,
        "strength": first.strength,
        "source_sha256": None,
    }


def library() -> Path:
    return config.path(config.atlas().library_dir)


def load_passages() -> list[Passage]:
    p = library() / "passages.jsonl"
    if not p.exists():
        raise StageError("no atlas passages; run `econ atlas-ingest`")
    return [
        Passage.model_validate_json(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_notes() -> dict[str, str]:
    p = library() / "notes.jsonl"
    return {
        r["chunk_id"]: r["context"] for r in (json.loads(x) for x in p.read_text().splitlines() if x.strip())
    }


def ingest(run: Run, *, from_path: str | None = None, ref: str | None = None, count_tokens=None) -> dict:
    """Read, check and write the atlas's passages and their notes."""
    jsonl, meta_bytes, origin = read_source(from_path, ref)
    passages, meta = validate(jsonl, meta_bytes, count_tokens=count_tokens)
    lib = library()
    write_text_atomic(lib / "passages.jsonl", jsonl.decode("utf-8"))
    notes = [{"chunk_id": p.passage_id, "context": note(p)} for p in passages]
    for n in notes:
        if textcheck.high(textcheck.scan(n["context"])):
            raise StageError("a note failed the text checks", item=n["chunk_id"])
    write_text_atomic(
        lib / "notes.jsonl", "".join(json.dumps(n, sort_keys=True, ensure_ascii=False) + "\n" for n in notes)
    )
    kinds: dict[str, int] = {}
    for p in passages:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    source = {
        "repo": config.atlas().source.repo,
        "ref": origin["ref"],
        "from": origin["from"],
        "dirty": origin["dirty"],
        "passages_version": meta["version"],
        "passages_sha256": meta["passages_sha256"],
        "atlas_sha256": meta["atlas_sha256"],
        "atlas_built": meta["built"],
        "base": meta.get("base"),
        "passages": len(passages),
        "documents": len({p.doc_id for p in passages}),
        "kinds": dict(sorted(kinds.items())),
        "notes": config.atlas().notes,
    }
    write_json_atomic(lib / "source.json", source)
    for f in ("passages.jsonl", "notes.jsonl", "source.json"):
        run.add_output(lib / f)
    run.counts.update(passages=len(passages), documents=source["documents"], **kinds)
    if origin["dirty"]:
        run.warn(
            "the checkout's evidence/data has uncommitted changes; ingest from a commit before indexing for Render"
        )
    return source
