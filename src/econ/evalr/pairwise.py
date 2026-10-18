"""Pairwise preference between two answer runs, by a judge from another family, in both orders.

For each need the judge sees the question, the narrative and both answers (prose, coverage, claims with
their quotes, gaps), labelled A and B, once in each order. A preference counts only when both orders
agree (SOP §12); the result is tested with a two-sided sign test. Replies are cached paid replies.
"""

from __future__ import annotations

import json
import math

from econ import config
from econ.answer import pipeline
from econ.evalr import llmcall
from econ.evalr.judged import Need

PROMPT = "pairwise-v1"
SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "winner": {"type": "string", "enum": ["A", "B", "tie"]}},
    "required": ["reason", "winner"],
    "additionalProperties": False,
}


def final_answer(row: dict) -> dict | None:
    return next((a["answer"] for a in reversed(row["attempts"]) if "answer" in a), None)


def render(label: str, ans: dict | None) -> str:
    if ans is None:
        return f'<answer label="{label}">(no answer)</answer>'
    claims = []
    for i, c in enumerate(ans["claims"], 1):
        quotes = " | ".join(f'[{q["evidence"]}] "{pipeline.defang(q["quote"])}"' for q in c["citations"])
        claims.append(f"  claim {i}: {pipeline.defang(c['text'])}\n    quotes: {quotes}")
    gaps = "; ".join(pipeline.defang(g) for g in ans["gaps"]) or "(none)"
    return (
        f'<answer label="{label}" coverage="{ans["coverage"]}">\n<prose>\n{pipeline.defang(ans["answer"])}\n</prose>\n'
        f"<claims>\n" + "\n".join(claims) + f"\n</claims>\n<gaps>{gaps}</gaps>\n</answer>"
    )


def calls(need: Need, a: dict, b: dict, *, model: str, effort: str) -> list[llmcall.Call]:
    system = (config.ROOT / "prompts" / "eval" / f"{PROMPT}.md").read_text(encoding="utf-8")
    head = f"<question>{pipeline.defang(need.question)}</question>\n<narrative>{pipeline.defang(need.narrative)}</narrative>\n\n"
    out = []
    for order, (x, y) in (("ab", (a, b)), ("ba", (b, a))):
        user = head + render("A", final_answer(x)) + "\n\n" + render("B", final_answer(y))
        out.append(
            llmcall.Call(
                model=model,
                system=system,
                user=user,
                schema=SCHEMA,
                schema_name="preference",
                effort=effort,
                max_output_tokens=4000,
                purpose=f"pairwise:{PROMPT}:{model}",
                tag=f"{need.id}:{order}",
            )
        )
    return out


def verdict(reply: dict) -> str | None:
    d = reply.get("data") if reply else None
    if isinstance(d, list) and d:
        d = d[0]
    w = d.get("winner") if isinstance(d, dict) else None
    return w if w in ("A", "B", "tie") else None


def combine(ab: str | None, ba: str | None) -> str:
    """'first', 'second', 'tie' or 'split' for the pair (first = the run shown as A in order ab)."""
    if ab is None or ba is None:
        return "missing"
    m = {"A": "first", "B": "second", "tie": "tie"}
    flip = {"A": "second", "B": "first", "tie": "tie"}
    x, y = m[ab], flip[ba]
    return x if x == y else "split"


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def save(name: str, rows: list[dict]) -> None:
    from econ.manifest import write_text_atomic

    p = config.path("eval/runs/answers") / f"{name}.jsonl"
    write_text_atomic(p, "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows))
