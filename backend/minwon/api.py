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
from minwon.agent import cancel, topic
from minwon.agent.brain import get_brain
from minwon.agent.graph import build_graph, revision_input, start_input
from minwon.settings import settings
from minwon.tools import export

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("minwon")

app = FastAPI(title="AI민원길잡이 API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

graph = build_graph()
# 세션 → 대화 기록(thread)과 되돌아갈 지점. 중단·실패하면 그 턴 직전 체크포인트로 되돌리고,
# 다른 종류의 민원으로 바뀌면 새 thread로 처음부터 시작한다.
sessions: dict[str, dict] = {}

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


def _session(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(404, "세션을 찾을 수 없습니다. 새 민원을 시작해 주세요.")
    return sessions[session_id]


def _config(session_id: str) -> dict:
    """이번 턴을 이어 갈 지점: 직전 턴을 중단했으면 그 직전 체크포인트, 아니면 최신 상태."""
    s = _session(session_id)
    base = s["rollback"] or {"configurable": {"thread_id": s["thread"]}}
    return {"configurable": {**base["configurable"], "session_id": session_id}}


def _latest(session_id: str) -> dict:
    return {"configurable": {"thread_id": _session(session_id)["thread"], "session_id": session_id}}


def _restore(session_id: str, previous: dict, before) -> None:
    """중단·실패한 턴을 없던 일로: 턴 시작 전 상태로 되돌린다 (첫 턴이면 빈 대화로)."""
    if before.values:
        sessions[session_id] = {"thread": previous["thread"], "rollback": before.config}
    else:
        sessions[session_id] = {"thread": uuid.uuid4().hex, "rollback": None}


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
    sessions[session_id] = {"thread": session_id, "rollback": None}
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    snapshot = graph.get_state(_config(session_id))
    pending = _pending(snapshot)
    status = "asking" if pending else ("ready" if snapshot.values else "new")
    return {"status": status, "pending": pending, **{k: snapshot.values.get(k) for k in SNAPSHOT_KEYS}}


def _run(session_id: str, text: str) -> Iterator[str]:
    _session(session_id)
    masked = safety.mask_pii(text)
    if masked.findings:
        yield _event(type="masked", text=masked.text, findings=masked.findings)
    # 위기 표현은 대화 어느 단계에서든 AI 판단보다 먼저, 정해진 문장으로 안내한다
    crisis = safety.is_crisis(masked.text)
    if crisis:
        yield _event(type="crisis", message=safety.CRISIS_NOTICE)

    previous = dict(sessions[session_id])
    config = _config(session_id)
    before = snapshot = graph.get_state(config)
    pending = _pending(snapshot)
    cancel.begin(session_id)
    stopped = failed = False
    try:
        # 질문에 답하는 중이거나 완성 후에 들어온 말 확인:
        # 다른 종류의 민원이면 새 민원으로 바꿔 처음부터, 관계없는 말이면 진행하지 않고 안내만 한다
        stage = "asking" if pending else "ready" if snapshot.values.get("package") else None
        turn = None
        if stage and topic.worth_checking(masked.text, stage):
            with cancel.scope(session_id):
                turn = topic.detect(snapshot.values, pending, masked.text)
        if turn and turn["kind"] == "off_topic":
            # 위기 표현이면 질문을 다시 들이밀지 않고, 하던 민원은 그대로 둔 채 쉬어 가게 한다
            reask = pending and not crisis
            yield _event(type="off_topic", stage=stage, crisis=crisis,
                         message=safety.CRISIS_REPLY["paused"] if crisis else topic.OFF_TOPIC_REPLY[stage],
                         reason=turn["reason"], source=turn["source"], error=turn["error"],
                         questions=pending["questions"] if reask else [],
                         options=pending.get("options", []) if reask else [])
            return
        if turn:
            sessions[session_id] = {"thread": uuid.uuid4().hex, "rollback": None}
            config = _config(session_id)
            snapshot, pending = graph.get_state(config), None
            yield _event(type="topic_changed", **{k: v for k, v in turn.items() if k != "kind"})

        intent = (snapshot.values.get("understanding") or {}).get("intent", "complaint")
        if pending:
            graph_input = Command(resume={"text": masked.text, "pii": masked.findings})
        elif snapshot.values.get("package"):
            graph_input = revision_input(masked.text)
        elif snapshot.values and intent != "complaint":
            # 직전 입력이 민원이 아니었으면 새로 시작. 불분명했던 말은 이어서 말한 내용과 합쳐서 판단한다
            text = f"{snapshot.values['user_input']}\n{masked.text}" if intent == "unclear" else masked.text
            sessions[session_id] = {"thread": uuid.uuid4().hex, "rollback": None}  # 중단하면 previous·before로 되돌아감
            config = _config(session_id)
            graph_input = start_input(text, masked.findings)
        elif snapshot.values:
            yield _event(type="error", code="session_busy", message="이전 처리가 끝나지 않았어요. '새 민원'으로 다시 시작해 주세요.")
            return
        else:
            graph_input = start_input(masked.text, masked.findings)

        for mode, chunk in graph.stream(graph_input, config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                status = chunk.pop("status")
                kind = {"start": "node_start", "tool_start": "tool_start", "tool_end": "tool_end"}[status]
                yield _event(type=kind, **chunk)
            else:
                for node, update in chunk.items():
                    if node != "__interrupt__":
                        yield _event(type="node_end", node=node, data=update or {})
            if cancel.requested(session_id):
                stopped = True
                break
    except cancel.Cancelled:
        stopped = True
    except Exception as e:
        log.exception("Agent 실행 실패")
        failed = True
        yield _event(type="error", code="agent_failed", message=f"처리 중 문제가 생겼어요. 같은 내용으로 다시 보내 주세요. ({type(e).__name__})")
    finally:
        cancel.finish(session_id)

    if stopped or failed:
        _restore(session_id, previous, before)
        if stopped:
            yield _event(type="cancelled", message="처리를 멈췄어요. 내용을 고쳐서 다시 보내 주세요.",
                         restored="asking" if _pending(before) else "ready" if before.values.get("package") else "new")
        return

    sessions[session_id]["rollback"] = None
    snapshot = graph.get_state(_latest(session_id))
    understanding = snapshot.values.get("understanding") or {}
    if pending := _pending(snapshot):
        yield _event(type="ask", questions=pending["questions"], options=pending.get("options", []))
    elif understanding.get("intent", "complaint") != "complaint":
        yield _event(type="redirect", intent=understanding["intent"], message=understanding["reply"])
    else:
        yield _event(type="ready", **{k: snapshot.values.get(k) for k in RESULT_KEYS})


@app.post("/api/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageIn):
    _session(session_id)
    return StreamingResponse(_run(session_id, body.text), media_type="application/x-ndjson")


@app.post("/api/sessions/{session_id}/cancel")
def cancel_message(session_id: str):
    """처리 중인 메시지를 멈춘다. 실행 중인 AI 호출은 바로 끝내고, 대화는 그 메시지를 보내기 전으로 돌아간다."""
    _session(session_id)
    return {"stopping": cancel.request(session_id)}


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

