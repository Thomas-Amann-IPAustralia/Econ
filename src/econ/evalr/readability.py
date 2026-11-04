"""How easy an answer is to read (D-040): deterministic, free, for comparing answer prompts on the same needs.

- words per sentence, and the share of sentences over 25 words;
- Flesch reading ease (higher is easier; plain English for adults is about 60, academic prose 30 or less), with
  syllables counted by a vowel-group rule, which is approximate but the same for every answer;
- jargon per 100 words: the analysts' terms the atlas uses that a reader without statistics would trip on;
- numbers per 100 words.

Claim markers, headings' marks and emphasis are removed first; the words are the reader's.
"""

from __future__ import annotations

import re

JARGON = [
    "hazard ratio", "standard deviation", "interval", "decile", "quintile", "percentile", "held together",
    "adjusted", "not detected", "observational", "descriptive", "coefficient", "correlation", "regression",
    "rate ratio", "median", "placebo", "resampling", "elasticity", "cohort", "confidence", "statistically",
    "raw", "covariate", "third factor", "sample", "log",
]  # fmt: skip
_SENT = re.compile(r"(?<=[.!?])\s+(?=[\"'“(*]?[A-Z0-9])")


def plain_text(answer: str) -> str:
    t = re.sub(r"\[\d{1,3}\]", "", answer)
    t = re.sub(r"^\s*#{1,4}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)
    return re.sub(r"[*_`]+", "", t)


def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 1
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def measure(answer: str) -> dict:
    text = plain_text(answer)
    sentences = [s for line in text.split("\n") for s in _SENT.split(line) if re.search(r"[A-Za-z]", s)]
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*|\d[\d,.%]*", text)
    n_w, n_s = len(words), max(1, len(sentences))
    lengths = [len(re.findall(r"\S+", s)) for s in sentences]
    syl = sum(syllables(w) for w in words if w[0].isalpha())
    low = text.lower()
    jargon = sum(len(re.findall(rf"\b{re.escape(j)}\b", low)) for j in JARGON)
    numbers = len(re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", re.sub(r"\b[UBMQ]\d+\b|FY\d{4}", "", text)))
    return {
        "words": n_w,
        "sentences": len(sentences),
        "words_per_sentence": round(n_w / n_s, 1),
        "long_sentence_share": round(sum(x > 25 for x in lengths) / n_s, 3),
        "reading_ease": round(206.835 - 1.015 * (n_w / n_s) - 84.6 * (syl / max(1, n_w)), 1),
        "jargon_per_100": round(100 * jargon / max(1, n_w), 2),
        "numbers_per_100": round(100 * numbers / max(1, n_w), 2),
    }
