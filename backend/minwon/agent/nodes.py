import re
from datetime import datetime

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from minwon import knowledge, safety
from minwon.agent.brain import get_brain
from minwon.agent.state import AgentState
from minwon.settings import settings
from minwon.tools import cases, regions
from minwon.tools import export
from minwon.tools.export import export_pdf, schedule_followup
from minwon.tools.kb import kb_lookup
from minwon.tools.locate import NEARBY_LABEL, find_nearby, geocode, resolve_candidate

MAX_CONFIRM_ROUNDS = 2

TOOL_TITLE = {
    "geocode": "위치 확인",
    "kb_lookup": "담당 부서·절차 조회",
    "case_search": "비슷한 민원 사례 조회",
    "schedule_followup": "처리 확인 일정 만들기",
    "export_pdf": "민원 패키지 PDF 만들기",
}
SOURCE_DETAIL = {
    "kakao": "카카오 로컬 API",
    "text_fallback": "대체 경로: 문장에서 지역 추출",
    "kb": "지식베이스",
    "kb+region": "지식베이스 + 지역 정보",
    "data_go_kr": "공공데이터포털 (국민권익위 민원 질의응답)",
    "generated": "파일 생성",
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

    steps = [s for s in plan["steps"] if s["action"] not in ("review", "deliver")]
    present = {s["action"] for s in steps}
    defaults = {
        "geocode": ("위치 확인", "관할 시·군·구를 정하려면 정확한 주소가 필요합니다.", "location" in required),
        "find_nearby": ("주변 기관 검색", "현장을 관할하는 기관을 찾습니다.", bool(nearby)),
        "kb_lookup": ("담당 부서·절차 조회", "처리 부서와 제출 창구를 확인합니다.", True),
        "case_search": ("비슷한 민원 사례 조회", "공공데이터에서 같은 유형의 민원을 어느 기관이 처리했는지 확인합니다.", True),
        "write": ("민원 초안 작성", "모은 정보로 민원과 증빙 목록을 만듭니다.", True),
    }
    must_precede = {"geocode": ("kb_lookup", "write"), "find_nearby": ("kb_lookup", "write"), "kb_lookup": ("write",),
                    "case_search": ("write",), "write": ()}
    for action, (title, reason, needed) in defaults.items():
        if needed and action not in present:
            index = next((i for i, s in enumerate(steps) if s["action"] in must_precede[action]), len(steps))
            steps.insert(index, {"action": action, "title": title, "reason": reason})
            present.add(action)
            fixes.append(f"'{title}' 단계 추가")
    closing = (("review", "초안 검증", "빠진 사실이나 개인정보가 없는지 확인합니다."),
               ("deliver", "결과물 만들기", "민원 패키지 PDF와 처리 결과 확인 일정 파일을 만듭니다."))
    for action, title, reason in closing:
        step = next((s for s in plan["steps"] if s["action"] == action), None)
        if step is None:
            fixes.append(f"'{title}' 단계 추가")
        steps.append(step or {"action": action, "title": title, "reason": reason})
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

    # 이름 없는 장소('창원 초등학교', '우리 아파트')는 위치가 확인된 것으로 보지 않고 한 번 더 묻는다
    location_text = next((f["value"] for f in result["facts"] if f["slot"] == "location"), "") or result["location_query"]
    vague = bool(location_text) and not regions.is_specific_place(location_text)
    if vague and ctx["can_ask"] and "location" not in ctx["asked"] and "location" in ctx["required_info"]:
        question = {"slot": "location", "text": f"말씀하신 '{location_text}'만으로는 정확한 곳을 찾기 어려워요. "
                    "장소 이름(예: ○○초등학교), 동 이름, 또는 도로명 주소를 알려 주세요."}
        result["questions"] = [question, *[q for q in result["questions"] if q["slot"] != "location"]][:3]
        result["facts"] = [f for f in result["facts"] if f["slot"] != "location"]
    result["location_vague"] = vague

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
    if state["info"]["questions"]:
        return "ask"
    actions = {s["action"] for s in state["plan"]["steps"]}
    return "locate" if "geocode" in actions else "act"


def _run_tool(node: str, calls: list[dict], tool: str, input_text: str, fn, *args) -> dict:
    """Tool 하나를 실행하고 시작·결과를 화면으로 실시간 전송한다."""
    writer = get_stream_writer()
    writer({"node": node, "status": "tool_start", "tool": tool, "title": _tool_title(tool), "input": input_text})
    result = fn(*args) | {"title": _tool_title(tool), "input": input_text}
    writer({"node": node, "status": "tool_end", "result": result})
    calls.append(result)
    return result


def _tool_logs(node: str, calls: list[dict]) -> list[dict]:
    logs = []
    for c in calls:
        detail = c["summary"]
        if c["retries"]:
            detail += f" (재시도 {c['retries']}회)"
        if c["error"]:
            detail += f" — {c['error']}"
        source = "rule_fallback" if c["source"] in ("text_fallback", "error") else "tool"
        logs.append(_log(node, f"Tool: {c['title']}", detail, source, tool=c["tool"], via=SOURCE_DETAIL.get(c["source"], c["source"])))
    return logs


def _user_text(state: AgentState) -> str:
    return " ".join(d["text"] for d in state["dialogue"] if d["role"] == "user")


def locate(state: AgentState) -> dict:
    """Tool Use: 위치 확인. 후보가 여러 곳이면 사용자에게 고르게 하도록 표시한다."""
    _started("locate")
    facts = {f["slot"]: f["value"] for f in state["info"]["facts"]}
    query = state.get("location_query") or state["info"]["location_query"] or facts.get("location", "")
    calls: list[dict] = []
    location = _run_tool("locate", calls, "geocode", query or "(위치 표현 없음)", geocode, query, _user_text(state))["data"]
    return {"location": location, "location_query": query, "location_confirmed": not location.get("ambiguous"),
            "tool_calls": calls, "log": _tool_logs("locate", calls)}


def route_after_locate(state: AgentState) -> str:
    if state["location"].get("ambiguous") and state.get("confirm_rounds", 0) < MAX_CONFIRM_ROUNDS:
        return "confirm_location"
    return "act"


def confirm_location(state: AgentState) -> dict:
    """Memory·Feedback: 위치 후보를 보여 주고 사용자가 고른 곳으로 확정한다 (모르면 새 장소 표현으로 다시 검색)."""
    candidates = state["location"]["candidates"]
    query = state.get("location_query", "")
    options = [{"value": str(i + 1), "label": f"{c['name'] or c['address']} · {c['address']}"} for i, c in enumerate(candidates)]
    question = {"slot": "location", "text": f"'{query}'에 해당하는 곳이 {len(candidates)}곳 있어요. 어느 곳인가요? "
                "번호를 고르거나, 더 정확한 장소 이름·주소를 알려 주세요."}
    reply = interrupt({"questions": [question], "options": options})
    text = reply["text"].strip()
    rounds = state.get("confirm_rounds", 0) + 1
    dialogue = [{"role": "agent", "text": question["text"], "slots": ["location"]}, {"role": "user", "text": text}]

    picked = None
    if m := re.match(r"^\s*(\d+)\s*(번)?\s*$", text):
        index = int(m.group(1)) - 1
        picked = candidates[index] if 0 <= index < len(candidates) else None
    else:
        picked = next((c for c in candidates if c["name"] and (c["name"] == text or c["name"] in text.split())), None)

    if picked:
        calls: list[dict] = []
        location = _run_tool("confirm_location", calls, "geocode", picked["name"] or picked["address"], resolve_candidate, picked, query)["data"]
        return {"location": location, "location_confirmed": True, "confirm_rounds": rounds, "dialogue": dialogue,
                "tool_calls": calls, "log": [_log("confirm_location", "위치 후보 확인", f"사용자가 고른 곳: {picked['name'] or picked['address']}"),
                                             *_tool_logs("confirm_location", calls)]}
    return {"location_query": text, "confirm_rounds": rounds, "dialogue": dialogue,
            "log": [_log("confirm_location", "위치 후보 확인", f"새 장소 표현으로 다시 검색: {text}")]}


def route_after_confirm(state: AgentState) -> str:
    return "act" if state.get("location_confirmed") else "locate"


def act(state: AgentState) -> dict:
    """Tool Use: 확인된 위치로 관할 기관을 찾고 담당 부서·절차를 조회한다. 실패하면 대체 경로로 이어 간다."""
    _started("act")
    plan = state["plan"]
    actions = [s["action"] for s in plan["steps"]]
    location = state.get("location") or {}
    calls: list[dict] = []
    nearby: dict[str, list[dict]] = {}

    def run(tool: str, input_text: str, fn, *args) -> dict:
        return _run_tool("act", calls, tool, input_text, fn, *args)

    if "find_nearby" in actions:
        for kind in plan["nearby_kinds"]:
            nearby[kind] = run(f"find_nearby:{kind}", location.get("address", ""), find_nearby, kind, location)["data"]

    u = state["understanding"]
    agencies = run("kb_lookup", u["category_label"], kb_lookup, u["category"], location, nearby)["data"]
    found = {}
    if "case_search" in actions:
        found = run("case_search", ", ".join(cases.queries(u["category"], u["keywords"])) or "-",
                    cases.similar_cases, u["category"], u["keywords"], location)["data"]
    logs = _tool_logs("act", calls)
    if location.get("ambiguous") and not state.get("location_confirmed"):
        logs.insert(0, _log("act", "위치 미확정", "후보가 여러 곳이라 1순위 후보로 진행 — 제출 전 사용자 확인 필요", "rule_fallback"))
    return {"nearby": nearby, "agencies": agencies, "cases": found, "tool_calls": calls, "log": logs}


def _facts(state: AgentState) -> list[dict]:
    return state["info"]["facts"]


def decide(state: AgentState) -> dict:
    """Reasoning: Tool 결과를 근거로 주 담당 기관·제출 창구·시민이 할 일을 정한다."""
    _started("decide")
    ag = state["agencies"]
    departments, channels = ag["departments"], ag["channels"]
    ctx = {
        "understanding": state["understanding"],
        "facts": _facts(state),
        "location": state.get("location", {}),
        "departments": departments,
        "channels": channels,
        "procedure": ag["procedure"],
        "period": ag["period"],
        "similar_cases": [{"title": c["title"], "agency": c["agency"]} for c in (state.get("cases") or {}).get("items", [])],
    }
    out = get_brain().call("decide", ctx)
    d = out.value.model_dump()

    fixes = []
    if not 0 <= d["primary"] < len(departments):
        d["primary"] = 0
        fixes.append("담당 기관 번호 보정")
    channel = next((c for c in channels if c["id"] == d["channel_id"]), None)
    if channel is None:
        channel = channels[0]
        fixes.append("제출 창구를 목록 안에서 다시 선택")
    primary = departments[d["primary"]]
    decision = {
        **d,
        "agency": primary,
        "channel": channel,
        "others": [x for i, x in enumerate(departments) if i != d["primary"]],
        "period": ag["period"],
        "fixes": fixes,
    }
    detail = f"{primary['agency']} {primary['unit']} · 제출 창구 {channel['name']}"
    if fixes:
        detail += f" (보정: {', '.join(fixes)})"
    update = {"decision": decision}

    # 검색어만 같고 다른 문제인 사례는 시민에게 보여 주지 않는다 (AI가 고른 번호만, 목록 밖 번호는 무시)
    found = state.get("cases") or {}
    items = found.get("items", [])
    if items:
        keep = [items[i] for i in dict.fromkeys(d["relevant_cases"]) if 0 <= i < len(items)]
        update["cases"] = found | {"items": keep, "excluded": len(items) - len(keep)}
        if len(keep) < len(items):
            detail += f" · 관련 없는 사례 {len(items) - len(keep)}건 제외"
    return update | {"log": [_log("decide", "담당 기관 판단", detail, out.source, error=out.error)]}


def draft(state: AgentState) -> dict:
    """민원 초안·증빙 체크리스트 작성. 검증 의견이나 사용자 수정 요청이 있으면 반영해 다시 쓴다."""
    _started("draft")
    previous = state.get("package")
    review = state.get("review") or {}
    revision = state.get("revision_request", "")
    review_issues = review.get("issues", []) if previous and not review.get("passed", True) and not revision else []
    rules = knowledge.agency_rules(state["understanding"]["category"])
    decision = state["decision"]
    ctx = {
        "understanding": state["understanding"],
        "facts": _facts(state),
        "required_info": state["plan"]["required_info"],
        "dialogue": state["dialogue"],
        "location": state.get("location", {}),
        "decision": {k: decision[k] for k in ("agency", "channel", "reason", "steps")},
        "kb": {"request": rules["request"], "evidence": rules["evidence"]},
        "review_issues": review_issues,
        "revision_request": revision,
        "previous_draft": {"title": previous["title"], "body": previous["body"]} if previous and (revision or review_issues) else None,
    }
    out = get_brain().call("write", ctx)
    package = out.value.model_dump() | {"version": (previous or {}).get("version", 0) + 1}

    if revision:
        title, detail = "초안 다시 작성 (사용자 수정 요청)", f"요청: {revision}"
    elif review_issues:
        title, detail = "초안 다시 작성 (검증 의견 반영)", " / ".join(review_issues)
    else:
        title, detail = "민원 초안 작성", package["title"]
    return {
        "package": package,
        "revision_request": "",
        "log": [_log("draft", title, f"{detail} → {len(package['body'])}자, 증빙 {len(package['evidence'])}개", out.source, error=out.error)],
    }


PHONE = re.compile(r"(?<!\d)(?:0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}|1\d{3}-\d{4})(?!\d)")
URL = re.compile(r"(?:https?://|www\.)[^\s)\]]+")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _rule_checks(state: AgentState, package: dict) -> tuple[dict, list[dict]]:
    checks = []

    # 개인정보 가림보다 먼저: 가려진 뒤에는 지어낸 연락처를 찾을 수 없다
    ag = state["agencies"]
    allowed_phones = {_digits(c["phone"]) for c in ag["channels"] if c["phone"]} | {_digits(d["phone"]) for d in ag["departments"] if d["phone"]}
    allowed_urls = {c["url"] for c in ag["channels"] if c["url"]}
    phones = [p for p in PHONE.findall(package["body"]) if _digits(p) not in allowed_phones]
    urls = [u for u in URL.findall(package["body"]) if not any(u.startswith(a) or a.endswith(u) for a in allowed_urls)]
    if phones or urls:
        what = ", ".join(x for x in (f"전화번호 {len(phones)}개" if phones else "", f"인터넷 주소 {len(urls)}개" if urls else "") if x)
        checks.append({"name": "연락처", "ok": False, "detail": f"확인되지 않은 {what}",
                       "issue": f"본문에 확인되지 않은 {what}가 있어요. 담당 기관 정보에 없는 연락처는 빼 주세요."})
    else:
        checks.append({"name": "연락처", "ok": True, "detail": "확인되지 않은 연락처 없음"})

    title, body = safety.mask_pii(package["title"]), safety.mask_pii(package["body"])
    found = title.findings + body.findings
    if found:
        package = package | {"title": title.text, "body": body.text}
        checks.append({"name": "개인정보", "ok": True, "detail": f"개인정보 {sum(f['count'] for f in found)}건을 자동으로 가림"})
    else:
        checks.append({"name": "개인정보", "ok": True, "detail": "개인정보 없음"})

    loc = state.get("location", {})
    fact_loc = next((f["value"] for f in _facts(state) if f["slot"] == "location"), "")
    terms = [loc.get("place_name"), loc.get("dong"), loc.get("legal_dong"), *(loc.get("sigungu", "").split()[-1:]), *fact_loc.split()[:2]]
    terms = [t for t in terms if t]
    if not terms or any(t in package["body"] for t in terms):
        checks.append({"name": "위치", "ok": True, "detail": "본문에 위치가 들어 있음" if terms else "확인된 위치 없음 (빈칸 안내)"})
    else:
        checks.append({"name": "위치", "ok": False, "detail": "본문에 위치가 없음",
                       "issue": f"본문에 민원 위치({terms[0]})를 넣어 주세요."})

    # 공식 요건이 아닌데 '필수'라고 쓴 증빙은 '권장'으로 낮춘다 (근거 없는 안내 방지)
    kb_required = [e for e in knowledge.agency_rules(state["understanding"]["category"])["evidence"] if e["level"] == "required"]
    evidence, unsupported = [], 0
    for e in package["evidence"]:
        if e["level"] == "required" and sum(x["level"] == "required" for x in evidence) >= len(kb_required):
            e = e | {"level": "recommended", "basis": ""}
            unsupported += 1
        elif e["level"] == "required" and not e["basis"]:
            e = e | {"basis": kb_required[0]["basis"]}
        evidence.append(e)
    package = package | {"evidence": evidence}
    checks.append({"name": "증빙 근거", "ok": True,
                   "detail": f"근거 없는 '필수' {unsupported}건을 '권장'으로 조정" if unsupported else "필수 표시는 공식 요건만"})

    length = len(package["body"])
    if length < 80:
        checks.append({"name": "분량", "ok": False, "detail": f"{length}자", "issue": "본문이 너무 짧아 상황이 전달되지 않아요. 현황을 더 써 주세요."})
    elif length > 1500:
        checks.append({"name": "분량", "ok": False, "detail": f"{length}자", "issue": "본문이 너무 길어요. 1,500자 안으로 줄여 주세요."})
    else:
        checks.append({"name": "분량", "ok": True, "detail": f"{length}자"})
    return package, checks


def review(state: AgentState) -> dict:
    """Feedback: 초안을 규칙 검사와 AI 검토로 확인하고, 문제가 있으면 다시 쓰게 한다."""
    _started("review")
    package, checks = _rule_checks(state, state["package"])
    issues = [c["issue"] for c in checks if not c["ok"]]

    source = "rule"
    error = ""
    brain = get_brain()
    if brain.mode == "llm":
        loc = state.get("location") or {}
        ctx = {"dialogue": state["dialogue"], "facts": _facts(state), "decision": {k: state["decision"][k] for k in ("agency", "reason")},
               "location": {k: loc.get(k, "") for k in ("address", "place_name", "sigungu", "dong")} if loc.get("address") else None,
               "draft": {"title": package["title"], "body": package["body"]}}
        out = brain.call("critique", ctx)
        source, error = out.source, out.error
        if out.source == "llm":
            ai_issues = out.value.issues if not out.value.passed else []
            issues += ai_issues
            checks.append({"name": "AI 검토", "ok": not ai_issues, "detail": " / ".join(ai_issues) or "고칠 점 없음"})
        else:
            checks.append({"name": "AI 검토", "ok": True, "detail": "AI 검토 실패 → 규칙 검사만 적용"})

    rounds = state.get("review_rounds", 0) + 1
    passed = not issues
    retry = not passed and rounds < settings.max_review_rounds
    result = {
        "passed": passed,
        "issues": issues,
        "checks": checks,
        "placeholders": export.blanks(package["body"]),
        "round": rounds,
        "retry": retry,
    }
    if passed:
        detail = f"통과 ({rounds}회차)"
    elif retry:
        detail = f"문제 {len(issues)}건 → 다시 작성"
    else:
        detail = f"문제 {len(issues)}건 남음 → 최대 횟수 도달, 사용자 확인 필요"
    return {"package": package, "review": result, "review_rounds": rounds,
            "log": [_log("review", "초안 검증", detail, source, error=error)]}


def route_after_review(state: AgentState) -> str:
    return "draft" if state["review"]["retry"] else "deliver"


def deliver(state: AgentState) -> dict:
    """Tool Use: 검증을 마친 민원 패키지를 PDF로, 처리 결과 확인일을 캘린더 일정 파일로 만든다."""
    _started("deliver")
    calls: list[dict] = []
    values = dict(state)
    followup = _run_tool("deliver", calls, "schedule_followup", state["decision"]["period"], schedule_followup, values)["data"]
    pdf = _run_tool("deliver", calls, "export_pdf", state["package"]["title"], export_pdf, values | {"files": {"ics": followup}})["data"]
    return {"files": {"ics": followup, "pdf": pdf}, "tool_calls": calls, "log": _tool_logs("deliver", calls)}


def route_entry(state: AgentState) -> str:
    return "draft" if state.get("revision_request") and state.get("package") else "guard"


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
