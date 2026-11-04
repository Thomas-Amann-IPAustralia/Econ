"""The answer check: deterministic, and it reads only what the model was shown (the evidence ledger).

- every citation names a passage that was shown;
- every quote is verbatim in that passage, after normalising typography, emphasis, case and spacing;
- each quote holds at least `min_quote_words` words and at most `max_quote_words`; a claim's quotes
  together hold at least `quote_claim_ratio` times the claim's words;
- the prose's markers and the claims match both ways;
- the coverage agrees with the claims and gaps;
- the output passes the text checks.

It guarantees that quotes are real and substantial. It does not judge whether a claim follows from its
quote: that needs a model that reads the passage (SOP §21.5), which is a later step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from econ import textcheck
from econ.answer.schema import Answer

MARKER = re.compile(r"\[(\d{1,3})\]")


@dataclass
class Located:
    evidence: int
    chunk_id: str | None
    quote: str
    found: bool
    start: int | None = None  # offsets in the passage's display text, for highlighting
    end: int | None = None
    words: int = 0


@dataclass
class Result:
    passed: bool
    errors: list[str] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "errors": self.errors, "claims": self.claims}


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    out, idx, space = [], [], True
    for i, ch in enumerate(text):
        n = " " if ch.isspace() else textcheck.normalise(ch)
        if n == "":
            continue
        if n == " ":
            if space:
                continue
            space = True
        else:
            space = False
        for c in n:
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def find_quote(passage: str, quote: str) -> tuple[int, int] | None:
    """Where a quote sits in a passage, tolerant of typography and spacing; None if it isn't there."""
    norm, idx = _norm_with_map(passage)
    q = re.sub(r"\s+", " ", textcheck.normalise(quote)).strip().strip(".…").strip()
    if not q:
        return None
    i = norm.find(q)
    if i < 0:
        # Models often elide with "...": accept when every fragment appears in order.
        parts = [p.strip() for p in re.split(r"\.\.\.+|…", q) if p.strip()]
        if len(parts) < 2:
            return None
        pos, first = 0, None
        for p in parts:
            j = norm.find(p, pos)
            if j < 0:
                return None
            first = j if first is None else first
            pos = j + len(p)
        return idx[first], idx[pos - 1] + 1
    return idx[i], idx[i + len(q) - 1] + 1


def words(s: str) -> int:
    return len(re.findall(r"\w+", s))


def check(
    ans: Answer,
    passages: dict[int, dict],
    *,
    min_quote_words: int,
    quote_claim_ratio: float,
    max_quote_words: int,
) -> Result:
    """`passages` maps evidence numbers to the chunks shown (with `chunk_id` and `text`)."""
    errors: list[str] = []
    claims_out = []
    n_claims = len(ans.claims)
    for ci, claim in enumerate(ans.claims, start=1):
        located, quote_words, claim_errors = [], 0, []
        if not claim.citations:
            claim_errors.append(f"claim [{ci}] has no citations")
        for cit in claim.citations:
            p = passages.get(cit.evidence)
            if p is None:
                claim_errors.append(f"claim [{ci}] cites evidence {cit.evidence}, which was not shown")
                located.append(Located(cit.evidence, None, cit.quote, False))
                continue
            span = find_quote(p["text"], cit.quote)
            w = words(cit.quote)
            loc = Located(
                cit.evidence, p["chunk_id"], cit.quote, span is not None, *(span or (None, None)), w
            )
            located.append(loc)
            if span is None:
                claim_errors.append(f"claim [{ci}]: the quote is not verbatim in evidence {cit.evidence}")
                continue
            if w < min_quote_words:
                claim_errors.append(
                    f"claim [{ci}]: a quote from evidence {cit.evidence} has {w} words; "
                    f"quotes need at least {min_quote_words}"
                )
            if w > max_quote_words:
                claim_errors.append(
                    f"claim [{ci}]: a quote from evidence {cit.evidence} has {w} words; "
                    f"quotes may have at most {max_quote_words}"
                )
            quote_words += w
        if claim.citations and quote_words < quote_claim_ratio * words(claim.text):
            claim_errors.append(
                f"claim [{ci}]: its quotes hold {quote_words} words for a claim of "
                f"{words(claim.text)}; quote enough to show the claim"
            )
        errors.extend(claim_errors)
        claims_out.append(
            {
                "n": ci,
                "text": claim.text,
                "verified": not claim_errors,
                "errors": claim_errors,
                "citations": [loc.__dict__ for loc in located],
            }
        )

    used = {int(m) for m in MARKER.findall(ans.answer)}
    unknown = sorted(m for m in used if m < 1 or m > n_claims)
    unused = sorted(set(range(1, n_claims + 1)) - used)
    if unknown:
        errors.append(f"the prose uses markers {unknown}, but there are {n_claims} claims")
    if unused:
        errors.append(f"claims {unused} are never marked in the prose")

    if ans.coverage == "not_in_kb":
        if ans.claims:
            errors.append("coverage is not_in_kb, but the answer makes claims")
        if not ans.gaps:
            errors.append("coverage is not_in_kb; say what is missing in gaps")
    elif ans.coverage == "complete" and ans.gaps:
        errors.append("coverage is complete, but gaps are listed; use partial")
    elif ans.coverage == "partial" and not ans.gaps:
        errors.append("coverage is partial; list what is missing in gaps")
    if ans.coverage != "not_in_kb" and not ans.claims:
        errors.append(f"coverage is {ans.coverage}, but the answer makes no claims")

    output = " ".join([ans.answer, *(c.text for c in ans.claims), *ans.gaps, *getattr(ans, "follow_ups", [])])
    for f in textcheck.high(textcheck.scan(output)):
        errors.append(f"the output failed a text check ({f.rule})")
    return Result(passed=not errors, errors=errors, claims=claims_out)


# --- the atlas's numbers rule (D-038) ------------------------------------------------------------------------

# A number: an optional sign, digits with optional thousands commas, an optional decimal part, and an optional
# per cent. Not a number: digits inside a word or an id (M40, FY2010, Q2, U44), or a section's or stage's number.
_NUMBER = re.compile(
    r"(?<![\w.,])([+\-−]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w])(\s*(?:%|per\s+cent\b|percent\b))?",
    re.IGNORECASE,
)
_NOT_A_FINDING = re.compile(
    r"(?:\b(?:stages?|steps?|sections?|questions?|views?|chapters?|parts?|tables?|figures?|"
    r"observations?|lens|claims?|evidence|passages?)\s+|\[)$",
    re.IGNORECASE,
)


def numbers_in(text: str, *, skip_labels: bool = False) -> list[tuple[str, bool, bool]]:
    """Each number in `text` as (value without commas or sign, negative, per cent). With `skip_labels`, a number
    that only labels something ("Stage 3", "section 1.2", "[2]") is left out."""
    out = []
    for m in _NUMBER.finditer(text):
        if skip_labels and _NOT_A_FINDING.search(text[: m.start()]):
            continue
        sign, whole, frac, pct = m.groups()
        frac = (frac or "").rstrip("0").rstrip(".")  # 6.0 is 6, as the charts' tables write it
        value = whole.replace(",", "") + frac
        out.append((value, sign in ("-", "−"), bool(pct)))
    return out


def numbers_check(claims: list[dict], ans) -> list[str]:
    """Every number a claim states must appear in the sentences it cites (the atlas's numbers rule: a number not
    on the page is not a finding). A number written without a sign or per cent matches the same digits with
    either; one written with a sign or per cent needs the same in a quote. Commas, "per cent" and the Unicode
    minus are normalised."""
    errors = []
    for ci, claim in enumerate(ans.claims, start=1):
        quoted = [n for cit in claim.citations for n in numbers_in(cit.quote)]
        for value, neg, pct in numbers_in(claim.text, skip_labels=True):
            ok = any(v == value and (not neg or qn) and (not pct or qp) for v, qn, qp in quoted)
            if not ok:
                shown = ("-" if neg else "") + value + ("%" if pct else "")
                errors.append(f"claim [{ci}] states {shown}, which is not in the sentences it cites")
    if errors:
        for c in claims:
            if any(e.startswith(f"claim [{c['n']}] states") for e in errors):
                c["verified"] = False
                c["errors"] = c["errors"] + [e for e in errors if e.startswith(f"claim [{c['n']}] states")]
    return errors
