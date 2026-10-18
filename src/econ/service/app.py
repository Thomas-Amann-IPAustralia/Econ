"""The API service on Render: the front end on GitHub Pages calls it.

  GET  /api/health            build identity, the embedder's and the model's state; wakes the embedder
  GET  /api/catalogue         the documents in the knowledge base
  POST /api/ask               one question, streamed as server-sent events (econ.answer.pipeline)
  POST /api/search            retrieval only, as JSON
  GET  /api/chunk/{chunk_id}  one passage with its neighbours, to read around a citation

Run locally with `econ serve`. On Render: `uvicorn econ.service.app:app --host 0.0.0.0 --port $PORT`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from econ import config
from econ.answer import pipeline
from econ.answer.providers import configured
from econ.manifest import git_state
from econ.retrieval.index import EmbedderClient, Index


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(max_length=6000)


class AskIn(BaseModel):
    question: str = Field(min_length=2)
    history: list[Turn] = []
    context: str = ""
    doc_ids: list[str] | None = None
    years: tuple[int, int] | None = None


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    doc_ids: list[str] | None = None
    years: tuple[int, int] | None = None


class Meter:
    """Daily spend, in memory. A restart forgets it, so the cap is a brake, not a guarantee."""

    def __init__(self, cap: float):
        self.cap, self.day, self.spent, self.lock = cap, "", 0.0, threading.Lock()

    def _roll(self):
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self.day:
            self.day, self.spent = today, 0.0

    def available(self) -> bool:
        with self.lock:
            self._roll()
            return self.spent < self.cap

    def add(self, usd: float):
        with self.lock:
            self._roll()
            self.spent += usd


class Limiter:
    def __init__(self, per_hour: int):
        self.per_hour, self.hits, self.lock = per_hour, defaultdict(deque), threading.Lock()

    def allow(self, client: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[client]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= self.per_hour:
                return False
            q.append(now)
            return True


def client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def create_app() -> FastAPI:
    scfg = config.service()
    index = Index()
    embedder = EmbedderClient()
    found = configured()
    model, provider = found if found else (None, None)
    meter = Meter(scfg.llm.daily_budget_usd)
    limiter = Limiter(scfg.limits.requests_per_hour_per_client)
    build = {
        "commit": os.environ.get("RENDER_GIT_COMMIT") or git_state()["commit"],
        "index": index.meta,
        "prompt": scfg.answer.prompt,
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    def warm_embedder():
        if embedder.configured and not embedder.warm and not embedder.pinging:
            threading.Thread(target=embedder.ping, daemon=True).start()

    warm_embedder()  # Render wakes first; wake Cloud Run alongside it

    app = FastAPI(title="Econ knowledge base", docs_url="/api/docs", redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=scfg.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=3600,
    )

    @app.get("/api/health")
    def health() -> dict:
        warm_embedder()
        return {
            "status": "ok",
            "build": build,
            "embedder": {"configured": embedder.configured, "warm": embedder.warm, "health": embedder.health},
            "llm": {
                "mode": "answer" if model and meter.available() else "evidence_only",
                "provider": getattr(provider, "name", None),
                "answer_model": getattr(provider, "answer_model", None),
                "plan_model": getattr(provider, "plan_model", None),
                "budget_reached": bool(model) and not meter.available(),
            },
        }

    @app.get("/api/catalogue")
    def catalogue() -> dict:
        return {"documents": index.docs, "index": index.meta}

    @app.get("/api/chunk/{chunk_id}")
    def chunk(chunk_id: str) -> dict:
        i = index.by_id.get(chunk_id)
        if i is None:
            raise HTTPException(404, "no such chunk")
        c = index.chunks[i]
        prev = (
            index.chunks[i - 1]["chunk_id"]
            if i > 0 and index.chunks[i - 1]["doc_id"] == c["doc_id"]
            else None
        )
        nxt = (
            index.chunks[i + 1]["chunk_id"]
            if i + 1 < len(index.chunks) and index.chunks[i + 1]["doc_id"] == c["doc_id"]
            else None
        )
        return {**{k: v for k, v in c.items() if k != "embed_text"}, "prev": prev, "next": nxt}

    def services() -> pipeline.Services:
        use_model = model if (model and meter.available()) else None
        return pipeline.Services(
            index=index, embedder=embedder, model=use_model, provider=provider if use_model else None
        )

    def validate(body: AskIn, request: Request) -> pipeline.Request:
        lim = scfg.limits
        if not limiter.allow(client_id(request)):
            raise HTTPException(429, "too many questions from this address; try again within the hour")
        if len(body.question) > lim.max_question_chars:
            raise HTTPException(
                413,
                f"questions are limited to {lim.max_question_chars} characters; "
                "paste longer material into the context box",
            )
        if len(body.context) > lim.max_context_chars:
            raise HTTPException(413, f"pasted context is limited to {lim.max_context_chars} characters")
        if body.doc_ids:
            unknown = sorted(set(body.doc_ids) - set(index.docs))
            if unknown:
                raise HTTPException(400, f"unknown documents: {unknown}")
        return pipeline.Request(
            question=body.question,
            history=[t.model_dump() for t in body.history],
            context=body.context,
            doc_ids=body.doc_ids,
            years=body.years,
        )

    def record(req: pipeline.Request, events: list[dict]):
        done = next((e for e in events if e["event"] == "done"), {})
        meter.add(done.get("cost_usd", 0.0))
        if scfg.logging.record_questions:
            log = {
                "type": "answer",
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "commit": build["commit"],
                "question": req.question,
                "context_chars": len(req.context),
                "events": [{k: v for k, v in e.items() if k not in ("traces",)} for e in events],
            }
            print(json.dumps(log, ensure_ascii=False, default=str), flush=True)

    @app.post("/api/ask")
    def ask(body: AskIn, request: Request, stream: bool = True):
        req = validate(body, request)
        svc = services()
        if not stream:
            events = list(pipeline.run(req, svc))
            record(req, events)
            return JSONResponse({"events": events})

        def gen():
            events = []
            try:
                for e in pipeline.run(req, svc):
                    events.append(e)
                    yield f"event: {e['event']}\ndata: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
            except Exception as e:  # noqa: BLE001 - the client gets a final error event, never a hang
                err = {"event": "error", "stage": "service", "message": f"{type(e).__name__}"}
                events.append(err)
                yield f"event: error\ndata: {json.dumps(err)}\n\n"
            finally:
                record(req, events)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/search")
    def search(body: SearchIn, request: Request) -> dict:
        req = validate(AskIn(question=body.query, doc_ids=body.doc_ids, years=body.years), request)
        svc = pipeline.Services(index=index, embedder=embedder)
        return {"events": list(pipeline.run(req, svc))}

    return app


def __getattr__(name: str):
    if name == "app":
        return create_app()
    raise AttributeError(name)
