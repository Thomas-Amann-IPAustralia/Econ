"""Versioned prompts, locked with the schemas they were written for (prompts/versions.lock).

A change to a prompt or to a schema is a new version. Loading fails if a prompt's text or a schema has
drifted from the lock, so a silent edit can't reach the service.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from pydantic import BaseModel

from econ import config
from econ.answer.schema import Answer, AnswerV3, AnswerV5, Grades, Plan, schema_hash

PROMPTS = config.ROOT / "prompts"
SCHEMAS = {"answer": Answer, "answer3": AnswerV3, "answer5": AnswerV5, "filter": Grades, "plan": Plan}


def schema_kind(name: str) -> str:
    """The schema a prompt is written for: its kind, except that answer prompts from v3 add follow-ups and
    from v5 cite sentences by id instead of writing claims (D-026)."""
    kind, version = name.rsplit("-v", 1)
    if kind != "answer" or int(version) < 3:
        return kind
    return "answer5" if int(version) >= 5 else "answer3"


def shows_publisher(name: str) -> bool:
    """Prompts written for a corpus of two publishers see each passage's publisher (D-034): the answer
    prompt from v6, the filter prompt from v2."""
    kind, version = name.rsplit("-v", 1)
    return (kind == "answer" and int(version) >= 6) or (kind == "filter" and int(version) >= 2)


def schema_for(name: str) -> type[BaseModel]:
    return SCHEMAS[schema_kind(name)]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def current_lock() -> dict:
    lock = {}
    for p in sorted(PROMPTS.glob("*-v*.md")):
        name = p.stem
        kind = schema_kind(name)
        lock[name] = {
            "sha256": _sha(p.read_text(encoding="utf-8")),
            "schema": kind,
            "schema_sha256": schema_hash(SCHEMAS[kind]),
        }
    return lock


@lru_cache
def load(name: str) -> str:
    lock = json.loads((PROMPTS / "versions.lock").read_text())
    if name not in lock:
        raise RuntimeError(f"prompt {name} is not in prompts/versions.lock")
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    entry = lock[name]
    if _sha(text) != entry["sha256"]:
        raise RuntimeError(f"prompt {name} changed since it was locked; make a new version")
    if schema_hash(SCHEMAS[entry["schema"]]) != entry["schema_sha256"]:
        raise RuntimeError(
            f"the {entry['schema']} schema changed since {name} was locked; make a new version"
        )
    return text
