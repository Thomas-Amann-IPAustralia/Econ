"""Run manifests: one JSON file per command run, failed runs included, never deleted.

Each records the status, inputs and outputs with their SHA-256, upstream runs, counts, warnings, the
resolved config hash, the git commit and dirty flag, and package versions.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from econ.config import DEFAULT_CORPUS, ROOT, corpus_name, path, pipeline

# Paths whose changes are the outputs of commands, not code. Writing them doesn't make a run dirty.
GENERATED = ("library/", "manifests/", "reports/", "eval/runs/", "web/data/")

PACKAGES = ("numpy", "onnxruntime", "tokenizers", "docling", "torch", "sentence-transformers", "pypdfium2")


class StageError(Exception):
    """A loud failure: the CLI prints the one-line cause and exits with code 2."""

    def __init__(self, cause: str, item: str | None = None, report: str | None = None):
        super().__init__(cause)
        self.cause = cause
        self.item = item
        self.report = report


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def git_state() -> dict:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    commit = run("rev-parse", "HEAD").strip() or os.environ.get("RENDER_GIT_COMMIT", "unknown")
    status = [line[3:] for line in run("status", "--porcelain").splitlines() if line.strip()]
    dirty = [p for p in status if not p.startswith(GENERATED)]
    return {"commit": commit, "dirty": bool(dirty), "dirty_paths": dirty[:20]}


def versions() -> dict:
    out = {"python": platform.python_version()}
    for name in PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return out


def write_json_atomic(p: Path, obj, *, indent: int | None = 2) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, indent=indent, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tmp.replace(p)


def write_text_atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


@dataclass
class Run:
    command: str
    run_id: str
    config_hash: str
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    upstream: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    status: str = "running"
    error: dict | None = None

    def add_input(self, p: Path) -> None:
        self.inputs[str(p.relative_to(ROOT))] = sha256_file(p)

    def add_output(self, p: Path) -> None:
        self.outputs[str(p.relative_to(ROOT))] = sha256_file(p)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def manifest_path(self) -> Path:
        return path(pipeline().paths.manifests) / self.command / f"{self.run_id}.json"


def stage_name(command: str) -> str:
    """A command's manifest folder: `<command>` for the original corpus, `<corpus>/<command>` for another
    (D-033), so one corpus's runs are never taken for another's upstream."""
    c = corpus_name()
    return command if c == DEFAULT_CORPUS else f"{c}/{command}"


def latest_manifest(command: str, *, passed: bool = True) -> dict | None:
    d = path(pipeline().paths.manifests) / stage_name(command)
    if not d.exists():
        return None
    for p in sorted(d.glob("*.json"), reverse=True):
        m = json.loads(p.read_text())
        if not passed or m.get("status") == "passed":
            return m
    return None


def require_upstream(command: str) -> dict:
    """Check the previous stage passed and its outputs still match the disk."""
    m = latest_manifest(command)
    if m is None:
        raise StageError(f"no passed run of `{stage_name(command)}`; run it first")
    for rel, digest in m["outputs"].items():
        p = ROOT / rel
        if not p.exists():
            raise StageError(f"`{command}` output missing: {rel}", item=rel)
        if sha256_file(p) != digest:
            raise StageError(f"`{command}` output changed since its run: {rel}", item=rel)
    return m


@contextmanager
def run(command: str, config_hash: str, **params):
    """Wrap a stage: always writes a manifest, passed or failed."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command = stage_name(command)
    r = Run(command=command, run_id=run_id, config_hash=config_hash, params=params)
    # The code that ran is the code at the start; a commit made during a long run must not be mistaken
    # for it (the first chunking measurement recorded only the end state).
    git_start = git_state()
    started = time.time()
    try:
        yield r
        r.status = "passed"
    except StageError as e:
        r.status = "failed"
        r.error = {"cause": e.cause, "item": e.item, "report": e.report}
        raise
    except Exception as e:  # noqa: BLE001 - recorded, then re-raised
        r.status = "failed"
        r.error = {"cause": f"{type(e).__name__}: {e}"}
        raise
    finally:
        body = {
            "command": command,
            "run_id": run_id,
            "status": r.status,
            "error": r.error,
            "params": r.params,
            "config_hash": config_hash,
            "inputs": r.inputs,
            "outputs": r.outputs,
            "upstream": r.upstream,
            "counts": r.counts,
            "warnings": r.warnings,
            "git": git_start,
            "git_at_end": git_state(),
            "versions": versions(),
            "argv": sys.argv[1:],
            "seconds": round(time.time() - started, 1),
        }
        write_json_atomic(r.manifest_path, body)
