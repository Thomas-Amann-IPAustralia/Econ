"""Text checks: every item is untrusted input to a language model.

Used on source text (the sweep and the chunk stage), on model output, and on anything stored or returned.
A finding has a rule, a severity and an excerpt. High severity quarantines a source item unless the owner
has allowlisted it in config/allowlist.yaml (Claude never edits that file).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

# Invisible or direction-changing characters used to smuggle instructions past a reader.
_SMUGGLE = re.compile(
    "["
    "\U000e0000-\U000e007f"  # tag characters
    "‪-‮⁦-⁩"  # bidi embeddings, overrides and isolates
    "​-‍⁠﻿"  # zero-width characters and BOM
    "￹-￻"  # interlinear annotation
    "]"
)

# Phrases aimed at a model rather than a human reader.
_INJECTION = re.compile(
    r"(ignore (all |any )?(the )?(previous|prior|above) (instructions|prompts?)"
    r"|disregard (all |the )?(previous|prior|above)"
    r"|you are (now )?(an? )?(ai|assistant|language model|chatbot)\b"
    r"|system prompt|developer (message|mode)"
    r"|<\s*/?\s*(system|assistant|evidence|tool_result|instructions?)\s*>"
    r"|\bdo not (tell|reveal|mention) (the )?user)",
    re.IGNORECASE,
)

_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abpr]-[A-Za-z0-9-]{10,})"
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # high | medium | low
    excerpt: str

    def as_dict(self) -> dict:
        return asdict(self)


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    s = text[max(0, start - pad) : end + pad]
    return s.encode("unicode_escape").decode("ascii")[:200]


def scan(text: str) -> list[Finding]:
    out: list[Finding] = []
    for m in _SMUGGLE.finditer(text):
        # A lone BOM or zero-width joiner in extracted PDF text is common and harmless; runs are not.
        run = re.match(_SMUGGLE.pattern + "+", text[m.start() :])
        length = len(run.group(0)) if run else 1
        if "\U000e0000" <= m.group(0) <= "\U000e007f" or "‪" <= m.group(0) <= "‮":
            out.append(Finding("unicode_smuggling", "high", _excerpt(text, m.start(), m.end())))
        elif length >= 3:
            out.append(Finding("zero_width_run", "medium", _excerpt(text, m.start(), m.end())))
    for m in _INJECTION.finditer(text):
        out.append(Finding("ai_directed_text", "high", _excerpt(text, m.start(), m.end())))
    for m in _SECRET.finditer(text):
        out.append(Finding("secret", "high", _excerpt(text, m.start(), m.start() + 6, pad=0) + "…"))
    for m in _EMAIL.finditer(text):
        out.append(Finding("email_address", "low", m.group(0)))
    # Deduplicate while keeping order.
    seen, unique = set(), []
    for f in out:
        if (f.rule, f.excerpt) not in seen:
            seen.add((f.rule, f.excerpt))
            unique.append(f)
    return unique


def high(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "high"]


def normalise(text: str) -> str:
    """Normalise for comparison: compatibility forms, typographic quotes and dashes, case and spacing."""
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_TYPOGRAPHY)
    t = re.sub(r"[*_`]+", "", t)  # markdown emphasis
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


_TYPOGRAPHY = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "′": "'",
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        "­": "",
        "…": "...",
    }
)
