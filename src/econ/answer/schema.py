"""The answer's fixed structure, the query plan's and the relevance filter's. All are sent to the model as
strict JSON schemas.

The answer:
- `coverage`: complete | partial | not_in_kb. `not_in_kb` is a first-class answer.
- `answer`: Markdown prose. Each sentence that states something from the evidence ends with one or more
  claim markers, [1] or [1][3], numbering the `claims` array from 1.
- `claims`: each with its text and citations; a citation names an evidence passage by number and quotes
  it verbatim.
- `gaps`: what the question asked that the evidence doesn't cover.

Changing these shapes is a new prompt version and the owner's decision: the UI and other callers read them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(_Strict):
    evidence: int = Field(description="The number of the evidence passage, as in <evidence n=...>.")
    quote: str = Field(description="Words copied exactly from that passage that show the claim.")


class Claim(_Strict):
    text: str = Field(description="One statement the answer makes, in your words.")
    citations: list[Citation]


class Answer(_Strict):
    coverage: Literal["complete", "partial", "not_in_kb"]
    answer: str = Field(description="Markdown prose with claim markers like [1] or [2][3].")
    claims: list[Claim]
    gaps: list[str] = Field(description="Parts of the question the evidence does not answer.")


class Plan(_Strict):
    standalone_question: str = Field(description="The user's latest question, rewritten to stand alone.")
    queries: list[str] = Field(description="One to four search queries for the knowledge base.")


class Grade(_Strict):
    id: str
    grade: int = Field(ge=0, le=3)


# The relevance filter's reply (D-018): a 0-3 rating for every passage id it was shown. Its strict schema is
# the one the filter was measured with (the judge's, econ.evalr.judge.SCHEMA); a docstring here would enter
# the schema as a description and change it.
class Grades(_Strict):
    grades: list[Grade]


def strict_schema(model: type[BaseModel]) -> dict:
    """The model's JSON schema in the strict subset both providers accept: every property required,
    no additional properties, no titles or defaults, $defs inlined."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object":
                out["additionalProperties"] = False
                out["required"] = list(out.get("properties", {}))
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)


def schema_hash(model: type[BaseModel]) -> str:
    return hashlib.sha256(json.dumps(strict_schema(model), sort_keys=True).encode()).hexdigest()[:16]
