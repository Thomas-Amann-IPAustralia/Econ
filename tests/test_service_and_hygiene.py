import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from econ import config
from econ.answer.prompts import current_lock, load
from econ.answer.schema import Answer, Plan, strict_schema
from econ.config import ROOT


@pytest.fixture
def client(index_dir, monkeypatch):
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "EMBEDDER_URL"):
        monkeypatch.delenv(k, raising=False)
    from econ.service.app import create_app

    return TestClient(create_app())


def test_module_app_is_built_once(index_dir, monkeypatch):
    import econ.service.app as service

    built = []
    monkeypatch.setattr(service, "_app", None)
    monkeypatch.setattr(service, "create_app", lambda: built.append(object()) or built[-1])
    assert service.app is service.app and len(built) == 1


def test_health_reports_build_and_evidence_only_mode(client):
    h = client.get("/api/health").json()
    assert h["llm"]["mode"] == "evidence_only" and h["build"]["index"]["strategy"] == "S384"
    assert h["embedder"]["configured"] is False


def test_ask_streams_events_and_json_mode_matches(client):
    r = client.post("/api/ask", json={"question": "design registrations"})
    assert r.headers["content-type"].startswith("text/event-stream")
    names = [line.split(": ", 1)[1] for line in r.text.splitlines() if line.startswith("event: ")]
    assert names == ["meta", "retrieval", "done"]
    j = client.post("/api/ask?stream=false", json={"question": "design registrations"}).json()
    assert j["events"][1]["dense"].startswith("not configured")


def test_chunk_endpoint_gives_neighbours(client):
    c = client.get("/api/chunk/doc-a:0001").json()
    assert c["prev"] == "doc-a:0000" and c["next"] == "doc-a:0002" and "embed_text" not in c
    assert client.get("/api/chunk/nope").status_code == 404


def test_cors_allows_only_the_pages_origin(client):
    ok = client.options(
        "/api/health",
        headers={
            "Origin": "https://thomas-amann-ipaustralia.github.io",
            "Access-Control-Request-Method": "GET",
        },
    )
    bad = client.options(
        "/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") and not bad.headers.get(
        "access-control-allow-origin"
    )


def test_limits_reject_oversize_and_unknown_documents(client):
    assert client.post("/api/ask", json={"question": "x" * 5000}).status_code == 413
    assert client.post("/api/ask", json={"question": "hello", "doc_ids": ["nope"]}).status_code == 400


def test_schemas_are_strict_everywhere():
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "object":
                assert n["additionalProperties"] is False and set(n["required"]) == set(n["properties"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    for m in (Answer, Plan):
        s = strict_schema(m)
        walk(s)
        assert "$ref" not in json.dumps(s)


def test_prompts_match_their_lock():
    lock = json.loads((ROOT / "prompts" / "versions.lock").read_text())
    assert lock == current_lock()
    assert load(config.service().answer.prompt)


def test_configs_load_and_every_model_is_priced():
    assert config.pipeline() and config.sources() and config.service()


def test_no_secrets_in_tracked_files_and_env_is_ignored():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    from econ.textcheck import _SECRET

    for f in files:
        p = ROOT / f
        if p.suffix in {".npy", ".npz", ".pdf", ".png"} or not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        assert not _SECRET.search(p.read_text(errors="ignore")), f
    assert ".env" not in files
    ignored = subprocess.run(["git", "check-ignore", ".env"], cwd=ROOT, capture_output=True, text=True)
    assert ignored.returncode == 0


def test_the_scripted_model_is_unreachable_from_service_config():
    names = {p.name for p in config.service().llm.providers}
    assert names <= {"openai", "gemini"}


def test_the_log_lists_every_passage_read_compactly():
    from econ.service.app import log_view

    e = {
        "event": "retrieval",
        "traces": [{"hits": []}],
        "evidence": [{"n": 1, "chunk_id": "a:1", "text": "kept"}],
        "pool": [
            {
                "chunk_id": "a:1",
                "search_rank": 1,
                "filter_grade": 3,
                "selected": True,
                "n": 1,
                "text": "t",
                "boxes": [],
            },
            {
                "chunk_id": "a:2",
                "search_rank": 2,
                "filter_grade": 0,
                "selected": False,
                "n": None,
                "text": "t",
            },
        ],
    }
    out = log_view(e)
    assert "traces" not in out and out["evidence"] == e["evidence"]
    assert out["pool"] == [
        {"chunk_id": "a:1", "search_rank": 1, "filter_grade": 3, "selected": True, "n": 1},
        {"chunk_id": "a:2", "search_rank": 2, "filter_grade": 0, "selected": False, "n": None},
    ]


def test_the_source_switches_limit_search_to_the_publishers_chosen(index_dir, monkeypatch):
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "EMBEDDER_URL"):
        monkeypatch.delenv(k, raising=False)
    docs = json.loads((index_dir / "docs.json").read_text())
    docs["doc-b"]["publisher"] = "Other"
    (index_dir / "docs.json").write_text(json.dumps(docs))
    from econ.service.app import create_app

    client = TestClient(create_app())

    def found(publishers):
        body = {"question": "design registrations among small firms", "publishers": publishers}
        events = client.post("/api/ask?stream=false", json=body).json()["events"]
        assert events[0]["publishers"] == publishers
        r = next(e for e in events if e["event"] == "retrieval")
        return {e["chunk_id"].split(":")[0] for e in r["evidence"]}

    assert found(None) == {"doc-a", "doc-b"}
    assert found(["Test", "Other"]) == {"doc-a", "doc-b"}
    assert found(["Other"]) == {"doc-b"} and found(["Test"]) == {"doc-a"}
    assert client.post("/api/ask", json={"question": "hello", "publishers": ["Nobody"]}).status_code == 400
