import json
import logging
import uuid
from collections.abc import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from minwon import safety
from minwon.agent.brain import get_brain
from minwon.agent.graph import build_graph, start_input
from minwon.settings import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("minwon")

app = FastAPI(title="AI민원길잡이 API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

graph = build_graph()
sessions: set[str] = set()

SNAPSHOT_KEYS = ("safety", "understanding", "plan", "info", "dialogue", "location", "nearby", "agencies", "tool_calls", "log")
RESULT_KEYS = ("info", "location", "agencies")


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _event(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _config(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(404, "세션을 찾을 수 없습니다. 새 민원을 시작해 주세요.")
    return {"configurable": {"thread_id": session_id}}


def _pending_questions(snapshot) -> list[dict] | None:
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value["questions"]
    return None


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "model": settings.model_label,
        "brain_mode": get_brain().mode,
        "kakao_enabled": bool(settings.kakao_rest_api_key),
    }


@app.post("/api/sessions")
def create_session():
    session_id = uuid.uuid4().hex
    sessions.add(session_id)
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    snapshot = graph.get_state(_config(session_id))
    questions = _pending_questions(snapshot)
    status = "asking" if questions else ("ready" if snapshot.values else "new")
    return {"status": status, "questions": questions, **{k: snapshot.values.get(k) for k in SNAPSHOT_KEYS}}


def _run(session_id: str, text: str) -> Iterator[str]:
    config = _config(session_id)
    masked = safety.mask_pii(text)
    if masked.findings:
        yield _event(type="masked", text=masked.text, findings=masked.findings)

    snapshot = graph.get_state(config)
    if _pending_questions(snapshot):
        graph_input = Command(resume={"text": masked.text, "pii": masked.findings})
    elif snapshot.values:
        yield _event(type="error", code="session_done", message="이 민원은 이미 처리가 끝났어요. '새 민원'으로 다시 시작해 주세요.")
        return
    else:
        graph_input = start_input(masked.text, masked.findings)

    try:
        for mode, chunk in graph.stream(graph_input, config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                status = chunk.pop("status")
                kind = {"start": "node_start", "tool_start": "tool_start", "tool_end": "tool_end"}[status]
                yield _event(type=kind, **chunk)
                continue
            for node, update in chunk.items():
                if node != "__interrupt__":
                    yield _event(type="node_end", node=node, data=update or {})
    except Exception as e:
        log.exception("Agent 실행 실패")
        yield _event(type="error", code="agent_failed", message=f"처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요. ({type(e).__name__})")
        return

    snapshot = graph.get_state(config)
    if questions := _pending_questions(snapshot):
        yield _event(type="ask", questions=questions)
    else:
        yield _event(type="ready", **{k: snapshot.values.get(k) for k in RESULT_KEYS})


@app.post("/api/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageIn):
    _config(session_id)
    return StreamingResponse(_run(session_id, body.text), media_type="application/x-ndjson")
