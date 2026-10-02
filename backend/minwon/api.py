import json
import logging
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from minwon import safety
from minwon.agent.brain import get_brain
from minwon.agent.graph import build_graph, revision_input, start_input
from minwon.settings import settings
from minwon.tools import export

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("minwon")

app = FastAPI(title="AI민원길잡이 API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

graph = build_graph()
sessions: set[str] = set()

SNAPSHOT_KEYS = (
    "safety", "understanding", "plan", "info", "dialogue", "location", "nearby", "agencies", "cases",
    "tool_calls", "decision", "package", "review", "files", "location_confirmed", "log",
)
RESULT_KEYS = ("info", "location", "location_confirmed", "agencies", "cases", "decision", "package", "review", "files")


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class DraftEdits(BaseModel):
    """사용자가 화면에서 고친 제목·본문 (PDF에 그대로 반영, 서버에 저장하지 않음)."""
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=5000)


def _event(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _config(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(404, "세션을 찾을 수 없습니다. 새 민원을 시작해 주세요.")
    return {"configurable": {"thread_id": session_id}}


def _pending(snapshot) -> dict | None:
    """멈춰 있는 질문 (questions, 위치 후보를 고를 때는 options 포함)."""
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "model": settings.model_label,
        "brain_mode": get_brain().mode,
        "kakao_enabled": bool(settings.kakao_rest_api_key),
        "data_go_kr_enabled": bool(settings.data_go_kr_service_key),
    }


@app.post("/api/sessions")
def create_session():
    session_id = uuid.uuid4().hex
    sessions.add(session_id)
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    snapshot = graph.get_state(_config(session_id))
    pending = _pending(snapshot)
    status = "asking" if pending else ("ready" if snapshot.values else "new")
    return {"status": status, "pending": pending, **{k: snapshot.values.get(k) for k in SNAPSHOT_KEYS}}


def _run(session_id: str, text: str) -> Iterator[str]:
    config = _config(session_id)
    masked = safety.mask_pii(text)
    if masked.findings:
        yield _event(type="masked", text=masked.text, findings=masked.findings)

    snapshot = graph.get_state(config)
    if _pending(snapshot):
        graph_input = Command(resume={"text": masked.text, "pii": masked.findings})
    elif snapshot.values.get("package"):
        graph_input = revision_input(masked.text)
    elif snapshot.values:
        yield _event(type="error", code="session_busy", message="이전 처리가 끝나지 않았어요. '새 민원'으로 다시 시작해 주세요.")
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
    if pending := _pending(snapshot):
        yield _event(type="ask", questions=pending["questions"], options=pending.get("options", []))
    else:
        yield _event(type="ready", **{k: snapshot.values.get(k) for k in RESULT_KEYS})


@app.post("/api/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageIn):
    _config(session_id)
    return StreamingResponse(_run(session_id, body.text), media_type="application/x-ndjson")


def _finished(session_id: str) -> dict:
    values = graph.get_state(_config(session_id)).values
    if not values.get("files"):
        raise HTTPException(409, "민원 패키지가 아직 완성되지 않았어요.")
    return values


def _download(content: bytes, media_type: str, filename: str) -> Response:
    disposition = f"attachment; filename=\"minwon{Path(filename).suffix}\"; filename*=UTF-8''{quote(filename)}"
    return Response(content, media_type=media_type, headers={"Content-Disposition": disposition})


def _pdf(session_id: str, title: str | None = None, body: str | None = None) -> Response:
    values = _finished(session_id)
    try:
        content, _pages = export.package_pdf(values, (title or "").strip() or None, (body or "").strip() or None)
    except export.ExportError as e:
        raise HTTPException(503, str(e)) from e
    return _download(content, "application/pdf", values["files"]["pdf"].get("name") or export.pdf_filename(values))


@app.get("/api/sessions/{session_id}/files/package.pdf")
def get_package_pdf(session_id: str):
    return _pdf(session_id)


@app.post("/api/sessions/{session_id}/files/package.pdf")
def post_package_pdf(session_id: str, edits: DraftEdits):
    return _pdf(session_id, edits.title, edits.body)


@app.get("/api/sessions/{session_id}/files/followup.ics")
def get_followup_ics(session_id: str):
    values = _finished(session_id)
    return _download(export.followup_ics(values).encode("utf-8"), "text/calendar; charset=utf-8", values["files"]["ics"]["name"])
