"""The reference tokenizer for chunk sizes, loaded from a pinned Hugging Face revision."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from econ import config


def hf_file(repo: str, revision: str, filename: str) -> Path:
    from huggingface_hub import hf_hub_download  # build extra

    return Path(
        hf_hub_download(
            repo, filename, revision=revision, cache_dir=str(config.path(config.pipeline().paths.models))
        )
    )


@lru_cache
def reference():
    from tokenizers import Tokenizer

    cfg = config.pipeline().chunking
    tok = Tokenizer.from_file(str(hf_file(cfg.tokenizer, cfg.tokenizer_revision, "tokenizer.json")))
    tok.no_truncation()
    tok.no_padding()
    return tok


def count(text: str) -> int:
    """Tokens including the two special tokens a BERT-style encoder adds."""
    return len(reference().encode(text, add_special_tokens=False).ids) + 2
