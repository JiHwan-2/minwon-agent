from datetime import datetime

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from minwon import knowledge, safety
from minwon.agent.brain import get_brain
from minwon.agent.state import AgentState
from minwon.settings import settings
from minwon.tools.kb import kb_lookup
from minwon.tools.locate import NEARBY_LABEL, find_nearby, geocode

TOOL_TITLE = {"geocode": "위치 확인", "kb_lookup": "담당 부서·절차 조회"}
SOURCE_DETAIL = {
    "kakao": "카카오 로컬 API",
    "text_fallback": "대체 경로: 문장에서 지역 추출",
    "kb": "지식베이스",
    "kb+region": "지식베이스 + 지역 정보",
    "skipped": "건너뜀",
    "error": "실패",
}


def _started(node: str) -> None:
    get_stream_writer()({"node": node, "status": "start"})


def _tool_title(tool: str) -> str:
    if tool.startswith("find_nearby:"):
        return f"주변 기관 검색 ({NEARBY_LABEL.get(tool.split(':', 1)[1], '')})"
    return TOOL_TITLE.get(tool, tool)


def _log(node: str, title: str, detail: str = "", source: str = "system", **extra) -> dict:
    return {"node": node, "title": title, "detail": detail, "source": source,
            "at": datetime.now().strftime("%H:%M:%S"), **extra}


def guard(state: AgentState) -> dict:
    """입력 안전 점검: 개인정보 가림 결과 기록, 긴급상황·지시 주입 감지."""
    _started("guard")
    text = state["user_input"]
    result = {
        "pii": state.get("pii_findings", []),
        "emergency": safety.is_emergency(text),
        "injection": safety.looks_like_injection(text),
    }
    notes = []
    if result["pii"]:
        notes.append("개인정보 " + ", ".join(f"{f['label']} {f['count']}건" for f in result["pii"]) + " 가림")
    if result["emergency"]:
        notes.append("긴급상황 표현 감지 → 112·119 신고 안내")
    if result["injection"]:
        notes.append("AI 지시 변경 시도 감지 → 자료로만 처리")
    return {"safety": result, "log": [_log("guard", "입력 안전 점검", " / ".join(notes) or "이상 없음")]}


def understand(state: AgentState) -> dict:
    """Goal: 생활불편 유형·핵심·긴급도 파악."""
    _started("understand")
    out = get_brain().call("understand", state["user_input"])
    data = out.value.model_dump()
    data["category_label"] = knowledge.category(data["category"])["label"]
    if state["safety"]["emergency"]:
        data["urgency"] = "high"
    return {
        "understanding": data,
        "log": [_log("understand", "문제 분석", f"{data['category_label']} · 긴급도 {data['urgency']}", out.source, error=out.error)],
    }


def _normalize_plan(plan: dict, cat: dict) -> tuple[dict, list[str]]:
    """LLM 계획이 필수 요소를 빠뜨렸으면 보정하고, 보정 내역을 남긴다."""
    fixes = []
    required = list(dict.fromkeys([*cat["required"], *plan["required_info"]]))
    if required != plan["required_info"]:
        fixes.append("유형별 필수 정보 추가")
    nearby = list(dict.fromkeys([*plan["nearby_kinds"], *cat["nearby"]]))
    if nearby != plan["nearby_kinds"]:
        fixes.append("주변 기관 검색 대상 추가")

    steps = [s for s in plan["steps"] if s["action"] != "review"]
    present = {s["action"] for s in steps}
    defaults = {
        "geocode": ("위치 확인", "관할 시·군·구를 정하려면 정확한 주소가 필요합니다.", "location" in required),
        "find_nearby": ("주변 기관 검색", "현장을 관할하는 기관을 찾습니다.", bool(nearby)),
        "kb_lookup": ("담당 부서·절차 조회", "처리 부서와 제출 창구를 확인합니다.", True),
        "write": ("민원 초안 작성", "모은 정보로 민원과 증빙 목록을 만듭니다.", True),
    }
    must_precede = {"geocode": ("kb_lookup", "write"), "find_nearby": ("kb_lookup", "write"), "kb_lookup": ("write",), "write": ()}
    for action, (title, reason, needed) in defaults.items():
        if needed and action not in present:
            index = next((i for i, s in enumerate(steps) if s["action"] in must_precede[action]), len(steps))
            steps.insert(index, {"action": action, "title": title, "reason": reason})
            present.add(action)
            fixes.append(f"'{title}' 단계 추가")
    review = next((s for s in plan["steps"] if s["action"] == "review"), None)
    if review is None:
        fixes.append("'초안 검증' 단계 추가")
    steps.append(review or {"action": "review", "title": "초안 검증", "reason": "빠진 사실이나 개인정보가 없는지 확인합니다."})
    return {**plan, "required_info": required, "nearby_kinds": nearby, "steps": steps}, fixes


def plan(state: AgentState) -> dict:
    """Planning: 처리 계획과 사용할 Tool 결정."""
    _started("plan")
    code = state["understanding"]["category"]
    cat = knowledge.category(code)
    ctx = {
        "user_input": state["user_input"],
        "understanding": state["understanding"],
        "유형별 기본 필수 정보": cat["required"],
        "유형별 기본 주변 기관": cat["nearby"],
    }
    out = get_brain().call("plan", ctx)
    result, fixes = _normalize_plan(out.value.model_dump(), cat)
    result["fixes"] = fixes
    detail = " → ".join(s["title"] for s in result["steps"])
    if fixes:
        detail += f" (보정: {', '.join(fixes)})"
    return {"plan": result, "log": [_log("plan", "처리 계획 수립", detail, out.source, error=out.error)]}


def check(state: AgentState) -> dict:
    """Reasoning: 필수 정보가 충분한지 판단하고 부족하면 질문을 만든다."""
    _started("check")
    rounds = state.get("rounds", 0)
    ctx = {
        "understanding": state["understanding"],
        "required_info": state["plan"]["required_info"],
        "slot_labels": {s: v["label"] for s, v in knowledge.slots().items()},
        "dialogue": state["dialogue"],
        "asked": state.get("asked", []),
        "can_ask": rounds < settings.max_question_rounds,
    }
    out = get_brain().call("check", ctx)
    result = out.value.model_dump()
    if not ctx["can_ask"]:
        result["questions"] = []
    result["questions"] = [q for q in result["questions"] if q["slot"] not in ctx["asked"]][:3]

    known = {f["slot"] for f in result["facts"]}
    result["unknown"] = [s for s in ctx["required_info"] if s not in known]
    if result["questions"]:
        detail = f"질문 {len(result['questions'])}개 필요: " + ", ".join(knowledge.slots()[q["slot"]]["label"] for q in result["questions"])
    elif result["unknown"]:
        detail = "질문 한도 도달 — 확인된 정보로 진행 (미확인: " + ", ".join(knowledge.slots()[s]["label"] for s in result["unknown"]) + ")"
    else:
        detail = "필수 정보 충분"
    return {"info": result, "log": [_log("check", "정보 충분성 판단", detail, out.source, error=out.error)]}


def route_after_check(state: AgentState) -> str:
    return "ask" if state["info"]["questions"] else "act"


def act(state: AgentState) -> dict:
    """Tool Use: 계획에 적힌 Tool을 순서대로 실행한다. 실패하면 재시도·대체 경로로 이어 간다."""
    _started("act")
    writer = get_stream_writer()
    plan = state["plan"]
    actions = [s["action"] for s in plan["steps"]]
    facts = {f["slot"]: f["value"] for f in state["info"]["facts"]}
    query = state["info"]["location_query"] or facts.get("location", "")
    context_text = " ".join(d["text"] for d in state["dialogue"] if d["role"] == "user")

    calls: list[dict] = []
    location: dict = {}
    nearby: dict[str, list[dict]] = {}

    def run(tool: str, input_text: str, fn, *args) -> dict:
        writer({"node": "act", "status": "tool_start", "tool": tool, "title": _tool_title(tool), "input": input_text})
        result = fn(*args) | {"title": _tool_title(tool), "input": input_text}
        writer({"node": "act", "status": "tool_end", "result": result})
        calls.append(result)
        return result

    if "geocode" in actions:
        location = run("geocode", query or "(위치 표현 없음)", geocode, query, context_text)["data"]

    if "find_nearby" in actions:
        for kind in plan["nearby_kinds"]:
            nearby[kind] = run(f"find_nearby:{kind}", location.get("address", ""), find_nearby, kind, location)["data"]

    agencies = run("kb_lookup", state["understanding"]["category_label"], kb_lookup,
                   state["understanding"]["category"], location, nearby)["data"]

    logs = []
    for c in calls:
        detail = c["summary"]
        if c["retries"]:
            detail += f" (재시도 {c['retries']}회)"
        if c["error"]:
            detail += f" — {c['error']}"
        source = "rule_fallback" if c["source"] in ("text_fallback", "error") else "tool"
        logs.append(_log("act", f"Tool: {c['title']}", detail, source, tool=c["tool"], via=SOURCE_DETAIL.get(c["source"], c["source"])))

    return {"location": location, "nearby": nearby, "agencies": agencies, "tool_calls": calls, "log": logs}


def ask(state: AgentState) -> dict:
    """Memory: 그래프를 멈추고 사용자 답변을 받아 대화 기록에 남긴다."""
    questions = state["info"]["questions"]
    reply = interrupt({"questions": questions})
    slots = [q["slot"] for q in questions]
    pii = reply.get("pii", [])
    detail = f"답변 받음 ({len(reply['text'])}자)"
    if pii:
        detail += " · 개인정보 " + ", ".join(f"{f['label']} {f['count']}건" for f in pii) + " 가림"
    return {
        "dialogue": [
            {"role": "agent", "text": "\n".join(q["text"] for q in questions), "slots": slots},
            {"role": "user", "text": reply["text"]},
        ],
        "asked": [*state.get("asked", []), *slots],
        "rounds": state.get("rounds", 0) + 1,
        "log": [_log("ask", "추가 질문·답변", detail)],
    }
