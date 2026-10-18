"""BM25 keyword search in plain numpy, so the service needs no search engine.

Tokens: NFKC, lower case, alphanumeric runs, English stop words removed, Snowball (Porter 2) stems.
Weights are precomputed per (term, chunk) and stored term-major, so a query sums a few short arrays.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from pathlib import Path

import numpy as np

K1, B = 1.2, 0.75
_WORD = re.compile(r"[a-z0-9]+")

STOP = frozenset(
    """a about above after again against all am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have
    having he her here hers herself him himself his how i if in into is it its itself just me more most my
    myself no nor not now of off on once only or other our ours ourselves out over own same she should so
    some such than that the their theirs them themselves then there these they this those through to too
    under until up very was we were what when where which while who whom why will with would you your
    yours yourself yourselves what's also may might must shall""".split()
)


_local = threading.local()


def _stemmer():
    """One stemmer per thread: a Snowball stemmer keeps the word it is working on in its own state, so a
    shared one corrupts stems (or raises IndexError) when the service's thread pool tokenises two queries
    at once (found in the answer evaluation's thread pool, D-013)."""
    st = getattr(_local, "stemmer", None)
    if st is None:
        import snowballstemmer

        st = _local.stemmer = snowballstemmer.stemmer("english")
    return st


def tokenize(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).lower()
    words = [w for w in _WORD.findall(t) if w not in STOP]
    return _stemmer().stemWords(words)


class BM25:
    def __init__(
        self, vocab: dict[str, int], indptr: np.ndarray, rows: np.ndarray, weights: np.ndarray, n: int
    ):
        self.vocab, self.indptr, self.rows, self.weights, self.n = vocab, indptr, rows, weights, n

    @classmethod
    def build(cls, texts: list[str]) -> BM25:
        docs = [tokenize(t) for t in texts]
        n = len(docs)
        lengths = np.array([len(d) for d in docs], dtype=np.float64)
        avgdl = lengths.mean() if n else 1.0
        postings: dict[str, dict[int, int]] = {}
        for i, d in enumerate(docs):
            for w in d:
                row = postings.setdefault(w, {})
                row[i] = row.get(i, 0) + 1
        # Ids follow the sorted vocabulary, so the index is byte-identical across runs.
        terms = sorted(postings)
        vocab = {w: j for j, w in enumerate(terms)}
        indptr = [0]
        rows_all, w_all = [], []
        for w in terms:
            post = postings[w]
            df = len(post)
            idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
            rows = np.array(sorted(post), dtype=np.int32)
            tf = np.array([post[r] for r in rows], dtype=np.float64)
            norm = K1 * (1 - B + B * lengths[rows] / avgdl)
            rows_all.append(rows)
            w_all.append((idf * tf * (K1 + 1) / (tf + norm)).astype(np.float32))
            indptr.append(indptr[-1] + len(rows))
        return cls(
            vocab,
            np.array(indptr, dtype=np.int64),
            np.concatenate(rows_all) if rows_all else np.zeros(0, np.int32),
            np.concatenate(w_all) if w_all else np.zeros(0, np.float32),
            n,
        )

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(self.n, dtype=np.float32)
        for w in set(tokenize(query)):
            tid = self.vocab.get(w)
            if tid is None:
                continue
            a, b = self.indptr[tid], self.indptr[tid + 1]
            out[self.rows[a:b]] += self.weights[a:b]
        return out

    def matched_terms(self, query: str, row: int) -> list[str]:
        """The query's stems that occur in one chunk: shown in the trace and used for highlights."""
        hits = []
        for w in sorted(set(tokenize(query))):
            tid = self.vocab.get(w)
            if tid is None:
                continue
            a, b = self.indptr[tid], self.indptr[tid + 1]
            seg = self.rows[a:b]
            k = np.searchsorted(seg, row)
            if k < len(seg) and seg[k] == row:
                hits.append(w)
        return hits

    def save(self, path: Path) -> None:
        np.savez(path, indptr=self.indptr, rows=self.rows, weights=self.weights, n=np.array([self.n]))
        path.with_suffix(".vocab.json").write_text(
            json.dumps(self.vocab, sort_keys=True, separators=(",", ":"))
        )

    @classmethod
    def load(cls, path: Path) -> BM25:
        z = np.load(path)
        vocab = json.loads(path.with_suffix(".vocab.json").read_text())
        return cls(vocab, z["indptr"], z["rows"], z["weights"], int(z["n"][0]))
