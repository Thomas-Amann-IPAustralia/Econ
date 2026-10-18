"""The spend ledger and its guard: every paid model call made by the eval tools is metered here.

- `ledger.jsonl` (committed) holds one line per paid call or batch: provider, model, purpose, usage
  buckets and cost. Its sum is the spend so far.
- `guard(provider, reserve)` refuses a call unless spend so far plus the call's reserve fits under the
  budget's cap (config/eval.yaml). Reserves are deliberately pessimistic estimates.
- The service's own daily cap (config/service.yaml) is separate: it meters callers, not evaluation.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache

import yaml
from pydantic import BaseModel, ConfigDict

from econ import config
from econ.manifest import StageError


class EvalCfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    budgets_usd: dict[str, float]
    cap_fraction: float = 0.96
    ledger: str = "eval/spend/ledger.jsonl"
    cache: str = "eval/cache/llm"


@lru_cache
def cfg() -> EvalCfg:
    return EvalCfg.model_validate(yaml.safe_load((config.CONFIG_DIR / "eval.yaml").read_text()))


def provider_of(model: str) -> str:
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if model.startswith(("gemini-", "gemma-")):
        return "gemini"
    raise ValueError(f"unknown provider for model {model!r}")


def entries() -> list[dict]:
    p = config.path(cfg().ledger)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def spent(provider: str) -> float:
    return round(sum(e["cost_usd"] for e in entries() if e["provider"] == provider), 6)


def guard(provider: str, reserve: float) -> None:
    budget = cfg().budgets_usd[provider]
    cap = budget * cfg().cap_fraction
    so_far = spent(provider)
    if so_far + reserve > cap:
        raise StageError(
            f"{provider} spend ${so_far:.4f} + reserve ${reserve:.4f} would exceed the cap "
            f"${cap:.2f} of the ${budget:.2f} budget",
            item=provider,
            report=cfg().ledger,
        )


def record(*, model: str, purpose: str, usage: dict, cost_usd: float, mode: str = "sync", n: int = 1) -> None:
    """Append one line. `usage` holds exclusive buckets (input, cached_input, output, reasoning)."""
    p = config.path(cfg().ledger)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": provider_of(model),
        "model": model,
        "purpose": purpose,
        "mode": mode,
        "calls": n,
        "usage": usage,
        "cost_usd": round(cost_usd, 6),
    }
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def summary() -> dict:
    out: dict = {}
    for e in entries():
        d = out.setdefault(e["provider"], {"spent": 0.0, "by_purpose": {}})
        d["spent"] = round(d["spent"] + e["cost_usd"], 6)
        d["by_purpose"][e["purpose"]] = round(d["by_purpose"].get(e["purpose"], 0.0) + e["cost_usd"], 6)
    for prov, b in cfg().budgets_usd.items():
        out.setdefault(prov, {"spent": 0.0, "by_purpose": {}})["budget"] = b
    return out
