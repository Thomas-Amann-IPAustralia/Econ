"""The judged test set (judged-v1): the silver known-item needs plus the exploratory needs, as one list.

Silver needs (eval/testset/silver-v1.yaml) keep their gold spans; exploratory needs
(eval/testset/explore-v1.yaml) have none and rely on graded judgments alone. Every need has a narrative
for the judge: the exploratory ones carry their own; the silver ones share a generic one, so the judge
never sees the passage a question was written from (the gold passage then tests the judge).
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from econ import config
from econ.evalr import testset

SILVER_NARRATIVE = (
    "The user wants a specific fact, figure, explanation or finding from IP Australia's economics "
    "publications. A passage is relevant if it states what the question asks for, or a substantial part of "
    "it; a passage on the same topic that does not answer it is at most 1."
)


@dataclass(frozen=True)
class Need:
    id: str
    family: str  # silver | explore
    kind: str
    question: str
    narrative: str
    split: str
    context: str = ""
    owner: bool = False
    golds: tuple = ()


def _context(n: dict) -> str:
    if n.get("context_file"):
        text = config.path(n["context_file"]).read_text(encoding="utf-8")
        # The owner's prompt files hold the question on the first line and the pasted material after it.
        return text.split("\n", 1)[1].strip() if "\n" in text else ""
    return (n.get("context") or "").strip()


def load(
    silver: str = "eval/testset/silver-v1.yaml", explore: str = "eval/testset/explore-v1.yaml"
) -> list[Need]:
    out = [
        Need(n.id, "silver", n.kind, n.question, SILVER_NARRATIVE, n.split, golds=n.golds)
        for n in testset.load(config.path(silver))
    ]
    data = yaml.safe_load(config.path(explore).read_text(encoding="utf-8"))
    seen = {n.id for n in out}
    for n in data["needs"]:
        if n["id"] in seen:
            raise ValueError(f"duplicate need id {n['id']}")
        seen.add(n["id"])
        out.append(
            Need(
                n["id"],
                "explore",
                n["kind"],
                " ".join(n["question"].split()),
                " ".join(n["narrative"].split()),
                testset.split_of(n["id"]),
                context=_context(n),
                owner=bool(n.get("owner")),
            )
        )
    return out
