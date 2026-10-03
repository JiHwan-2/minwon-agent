import re
from datetime import datetime

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from minwon import i18n, knowledge, safety
from minwon.agent import cancel, conversation
from minwon.agent.brain import get_brain
from minwon.agent.state import AgentState
from minwon.settings import settings
from minwon.tools import cases, export, offices, photo as photos, regions
from minwon.tools.export import export_pdf
from minwon.tools.kb import kb_lookup
from minwon.tools.locate import NEARBY_LABEL, find_nearby, from_coords, geocode, resolve_candidate

MAX_CONFIRM_ROUNDS = 2
MAX_PHOTO_ROUNDS = 2  # 사진 확인 질문에 예/아니요를 알 수 없는 답이 오면 한 번 더 묻는다

TOOL_TITLE = {
    "service_kb": "민원 안내 지식베이스 조회",
    "find_kiosks": "가까운 무인민원발급기 찾기",
    "check_hours": "지금 운영 여부 확인",
    "photo_meta": "사진 정보 읽기 (EXIF)",
    "reverse_geocode": "사진 위치 → 주소 확인",
    "geocode": "위치 확인",
    "kb_lookup": "담당 부서·절차 조회",
    "case_search": "비슷한 민원 사례 조회",
    "export_pdf": "민원 패키지 PDF 만들기",
}
SOURCE_DETAIL = {
    "kakao": "카카오 로컬 API",
    "kakao+data_go_kr": "카카오 로컬 API + 공공데이터포털 (행정안전부 무인민원발급기 정보)",
    "clock": "현재 시각·공휴일",
    "exif": "사진 정보(EXIF)",
    "text_fallback": "대체 경로: 문장에서 지역 추출",
    "kb": "지식베이스",
    "kb+region": "지식베이스 + 지역 정보",
    "data_go_kr": "공공데이터포털 (국민권익위 민원 질의응답)",
    "generated": "파일 생성",
    "skipped": "건너뜀",
    "error": "실패",
}


def _started(node: str) -> None:
    cancel.check()  # 앞 단계 중에 중단을 눌렀으면 다음 단계로 넘어가지 않는다
    get_stream_writer()({"node": node, "status": "start"})


def _tool_title(tool: str) -> str:
    if tool.startswith("find_nearby:"):
        return f"주변 기관 검색 ({NEARBY_LABEL.get(tool.split(':', 1)[1], '')})"
    if tool.startswith("find_offices:"):
        return f"가까운 {knowledge.office_kind(tool.split(':', 1)[1])['label']} 찾기"
    return TOOL_TITLE.get(tool, tool)


def _log(node: str, title: str, detail: str = "", source: str = "system", **extra) -> dict:
    return {"node": node, "title": title, "detail": detail, "source": source,
            "at": datetime.now().strftime("%H:%M:%S"), **extra}


def guard(state: AgentState) -> dict:
    """입력 안전 점검: 개인정보 가림 결과 기록, 긴급상황·위기 표현·지시 주입 감지."""
    _started("guard")
    text = state["user_input"]
    result = {
        "pii": state.get("pii_findings", []),
        "emergency": safety.is_emergency(text),
        "crisis": safety.is_crisis(text),
        "injection": safety.looks_like_injection(text),
    }
    notes = []
    if result["pii"]:
        notes.append("개인정보 " + ", ".join(f"{f['label']} {f['count']}건" for f in result["pii"]) + " 가림")
    if result["emergency"]:
        notes.append("긴급상황 표현 감지 → 112·119 신고 안내")
    if result["crisis"]:
        notes.append("위기 표현 감지 → 자살예방 상담전화 109 안내")
    if result["injection"]:
        notes.append("AI 지시 변경 시도 감지 → 자료로만 처리")
    return {"safety": result, "log": [_log("guard", "입력 안전 점검", " / ".join(notes) or "이상 없음")]}


def route_after_guard(state: AgentState) -> str:
    return "look" if state.get("photo") else "understand"


PHOTO_NOTE = "(현장 사진 있음"


def _citizen_text(text: str) -> str:
    """앞 턴에 붙인 사진 메모 줄을 뺀 시민의 말 (사진을 다시 볼 때 메모가 겹치지 않게)."""
    return "\n".join(line for line in text.split("\n") if not line.startswith(PHOTO_NOTE)).strip()


def _photo_text(state: AgentState, photo: dict, location: dict | None, *issues: str, scene: bool = False) -> dict:
    """사진으로 확인한 내용을 시민의 말과 합쳐 민원 흐름(문제 분석부터)이 읽을 첫 입력으로 만든다.
    scene: AI가 불편을 찾지 못했거나 시민의 답이 분명하지 않을 때, 뒤 단계(문제 분석·대화)가 사진에 무엇이 있었는지 알도록
    AI가 본 장면을 남긴다. 시민이 '예'로 확인했으면 확인한 불편만, '아니요'면 시민의 말만 쓴다."""
    lines = list(dict.fromkeys(s.strip() for s in (_citizen_text(state["user_input"]), *issues) if s and s.strip()))
    notes = ["현장 사진 있음"]
    if scene and (seen := photo.get("analysis", {}).get("scene", "").strip()):
        notes.append(f"AI가 본 사진 속 장면: {seen}")
    if location:
        notes.append(f"사진 촬영 위치: {location['address']} 부근")
    elif clues := photo.get("analysis", {}).get("location_clues", "").strip():
        notes.append(f"사진 속 위치 단서: {clues}")
    if when := photos.korean_time(photo.get("meta", {}).get("taken_at", "")):
        notes.append(f"사진 촬영 시각: {when}")
    text = "\n".join([*lines, f"({' · '.join(notes)})"])
    return {"user_input": text, "latest": text, "dialogue": [{"role": "user", "text": text, "kind": "photo"}]}


def look(state: AgentState) -> dict:
    """Perception: 현장 사진에서 촬영 위치·시각을 읽고(Tool), Claude가 사진 속 생활불편을 찾아 확인 질문을 만든다."""
    _started("look")
    photo = state["photo"]
    calls: list[dict] = []
    meta = _run_tool("look", calls, "photo_meta", photo.get("name") or "사진", photos.read_exif, photo["id"])["data"]

    update: dict = {}
    location = None
    if meta["gps"]:
        lat, lon = meta["gps"]["lat"], meta["gps"]["lon"]
        found = _run_tool("look", calls, "reverse_geocode", f"위도 {lat:.5f}, 경도 {lon:.5f}", from_coords, lat, lon)
        if found["ok"]:
            location = found["data"]
            update |= {"location": location, "location_query": location["address"], "location_confirmed": True}

    text = _citizen_text(state["user_input"])
    out = get_brain().call("look", {"text": text, "language": photo["language"]}, photos.image(photo["id"]))
    analysis = out.value.model_dump()
    if out.source == "llm" and analysis["relevant"] and analysis["question"].strip():
        mode, prompt = "confirm", ""
    elif text:
        mode, prompt = "done", ""  # 사진에서 불편을 찾지 못했지만 시민이 쓴 말이 있으면 그 말로 진행
    else:
        mode, prompt = "describe", "photo.describe.failed" if out.source != "llm" else "photo.describe.irrelevant"
    photo = {**photo, "meta": meta, "analysis": analysis, "mode": mode, "prompt": prompt, "rounds": 0}
    if mode == "done":
        update |= _photo_text(state, photo, location, scene=True)

    if out.source == "llm" and analysis["emergency"] and not state["safety"]["emergency"]:
        update["safety"] = {**state["safety"], "emergency": True, "photo_emergency": True}

    if out.source != "llm":
        detail = "사진을 분석하지 못함 → " + ("시민이 쓴 말로 진행" if text else "시민에게 설명을 부탁함")
    elif not analysis["relevant"]:
        detail = "사진에서 생활불편을 찾지 못함 → " + ("시민이 쓴 말로 진행" if text else "시민에게 설명을 부탁함")
    else:
        detail = f"{analysis['issue']} → 예/아니요로 확인"
    if location:
        detail += f" · 위치: 사진 촬영 위치({location['address']})"
    elif meta["gps"]:
        detail += " · 위치: 사진 좌표를 주소로 바꾸지 못해 대화로 확인"
    else:
        detail += " · 위치: 사진에 GPS 정보 없음 → 대화로 확인"
    if update.get("safety"):
        detail += " · 긴급상황으로 보이는 장면 → 112·119 신고 안내"
    # 판단 기록을 먼저 둔다 (화면의 작업 기록은 첫 기록으로 이 단계의 판단 주체를 표시)
    return {"photo": photo, **update, "tool_calls": calls,
            "log": [_log("look", "사진 분석", detail, out.source, error=out.error), *_tool_logs("look", calls)]}


def route_after_look(state: AgentState) -> str:
    return "understand" if state["photo"]["mode"] == "done" else "confirm_photo"


def _photo_buttons(lang: str) -> dict[str, str]:
    """화면의 예/아니요 버튼으로 보낸 답 (4개 언어 모두 받는다. 화면 언어를 바꿨을 수 있음)."""
    return {i18n.t(f"photo.{a}", code).lower(): a for a in ("yes", "no") for code in i18n.LANGS}


def confirm_photo(state: AgentState) -> dict:
    """Feedback: 사진으로 짐작한 불편이 맞는지 시민에게 묻고, 답이 '예'인지 '아니요'인지 판단해 민원으로 이어 간다."""
    photo = state["photo"]
    lang, analysis = photo["language"], photo["analysis"]
    if photo["mode"] == "confirm":
        question = analysis["question"] if photo["rounds"] == 0 else i18n.t("photo.reask", lang, question=analysis["question"])
        options = [{"value": i18n.t(f"photo.{a}", lang), "label": i18n.t(f"photo.{a}", lang)} for a in ("yes", "no")]
    else:
        question, options = i18n.t(photo["prompt"], lang), []
    reply = interrupt({"kind": "photo", "questions": [{"slot": "detail", "text": question}], "options": options})
    text = reply["text"].strip()
    photo = {**photo, "rounds": photo["rounds"] + 1}
    location = state.get("location") if (state.get("location") or {}).get("from_photo") else None

    if photo["mode"] == "describe":
        rejected = photo.get("answer") == "no"  # 시민이 아니라고 한 짐작의 장면은 남기지 않는다 (문제 분석이 끌려가지 않게)
        photo |= {"mode": "done", "answer": "described"}
        return {"photo": photo, **_photo_text(state, photo, location, text, scene=not rejected),
                "log": [_log("confirm_photo", "사진 설명 받음", f"시민이 설명한 불편: {text}")]}

    if (button := _photo_buttons(lang).get(text.lower())) is not None:
        answer, issue, reason, source, error = button, "", "화면의 버튼으로 답함", "rule", ""
    else:
        out = get_brain().call("photo_answer", {"question": analysis["question"], "scene": analysis["scene"],
                                                "reply": text, "language": lang})
        answer, issue, reason, source, error = out.value.answer, out.value.issue, out.value.reason, out.source, out.error

    said = f"'{text}' → {dict(yes='예', no='아니요', unclear='알 수 없음')[answer]} ({reason})"
    if answer == "yes":
        photo |= {"mode": "done", "answer": "yes"}
        return {"photo": photo, **_photo_text(state, photo, location, analysis["issue"], issue),
                "log": [_log("confirm_photo", "사진 확인 답변", f"{said} → 사진 속 불편으로 민원 진행", source, error=error)]}
    if answer == "no" and issue:
        photo |= {"mode": "done", "answer": "no"}
        return {"photo": photo, **_photo_text(state, photo, location, issue),
                "log": [_log("confirm_photo", "사진 확인 답변", f"{said} → 시민이 말한 불편으로 진행", source, error=error)]}
    if answer == "no":
        photo |= {"mode": "describe", "prompt": "photo.describe.no", "answer": "no"}
        return {"photo": photo, "log": [_log("confirm_photo", "사진 확인 답변", f"{said} → 어떤 점이 불편한지 다시 묻기", source, error=error)]}
    if photo["rounds"] < MAX_PHOTO_ROUNDS:
        return {"photo": photo, "log": [_log("confirm_photo", "사진 확인 답변", f"{said} → 한 번 더 묻기", source, error=error)]}
    photo |= {"mode": "done", "answer": "unclear"}
    return {"photo": photo, **_photo_text(state, photo, location, text, scene=True),
            "log": [_log("confirm_photo", "사진 확인 답변", f"{said} → 답한 말 그대로 민원 흐름에서 판단", source, error=error)]}


def route_after_confirm_photo(state: AgentState) -> str:
    return "understand" if state["photo"]["mode"] == "done" else "confirm_photo"


INTENT_LABEL ={"referral": "다른 창구가 맞는 일", "unclear": "불분명한 입력", "not_complaint": "민원이 아닌 입력"}


def _language(state: AgentState) -> str:
    """시민의 언어 코드 (문제 분석에서 정함)."""
    return (state.get("understanding") or {}).get("language", "ko")


def understand(state: AgentState) -> dict:
    """Goal: 먼저 도와줄 생활불편인지 판단하고, 맞으면 유형·핵심·긴급도를 파악한다."""
    _started("understand")
    out = get_brain().call("understand", state["user_input"])
    data = out.value.model_dump()
    data["category_label"] = knowledge.category(data["category"])["label"]
    # 시민의 언어: Claude 판단. Claude가 실패했고 글자 모양으로도 모르면(라틴 문자) 화면에서 고른 언어를 쓴다
    data["language"] = i18n.normalize(data["language"]) or "ko"
    if out.source != "llm" and not i18n.detect(state["user_input"]):
        data["language"] = i18n.normalize(state.get("lang_hint")) or data["language"]
    data["language"] = lang = i18n.ui_lang(data["language"])  # 지원하지 않는 언어는 영어로 안내
    if state["safety"]["emergency"]:
        data |= {"intent": "complaint", "urgency": "high"}  # 긴급상황 표현은 민원 흐름으로 (112·119 안내는 guard가 함)
    if data["intent"] == "referral" and data["referral"] == "none":
        data["intent"] = "complaint"  # 창구를 고르지 못했으면 지금처럼 민원 흐름으로
    if data["intent"] == "service" and data["service"] == "none":
        # 맞는 민원 서비스를 고르지 못했으면 무엇을 하려는지 되묻는다
        data |= {"intent": "unclear", "reply": data["reply"].strip() or i18n.t("reply.unclear", lang)}
    if data["intent"] != "referral":
        data["referral"] = "none"
    if data["intent"] != "service":
        data["service"] = "none"
    if data["intent"] == "service":
        s = knowledge.service(data["service"])
        data["service_group"] = s["group"]
        detail = f"민원 서비스 안내: {s['label']} [{knowledge.service_groups()[s['group']]['label']}] → 가까운 기관·받는 방법 안내"
        return {"understanding": data, "log": [_log("understand", "입력 확인", detail, out.source, error=out.error)]}

    if data["intent"] == "referral":
        # 창구 이름·번호·주소는 Claude가 쓰지 않고 지식베이스(공식 안내로 확인한 값)에서 가져온다
        ref = knowledge.referral(data["referral"], lang)
        data["referral_info"] = ref
        data["reply"] = i18n.t("referral.reply", lang, label=ref["label"], agency=ref["agency"], first=ref["first"])
        ko = knowledge.referral(data["referral"])
        detail = f"{INTENT_LABEL['referral']}({ko['label']}) → {ko['agency']} 안내, 민원 흐름을 시작하지 않음"
        return {"understanding": data, "log": [_log("understand", "입력 확인", detail, out.source, error=out.error)]}
    if data["intent"] != "complaint":
        if state["safety"].get("crisis"):
            # 109 안내(api가 먼저 보냄)에 이어 생활불편 예시를 들지 않고 정해진 문장으로만 답한다
            data["reply"] = i18n.t("crisis.reply.new", lang)
            detail = f"{INTENT_LABEL[data['intent']]} · 위기 표현 → 상담전화 안내 후 민원 흐름을 시작하지 않음"
        else:
            data["reply"] = data["reply"].strip() or i18n.t(f"reply.{data['intent']}", lang)
            detail = f"{INTENT_LABEL[data['intent']]} → 민원 흐름을 시작하지 않고 안내"
        return {"understanding": data, "log": [_log("understand", "입력 확인", detail, out.source, error=out.error)]}

    return {
        "understanding": data,
        "log": [_log("understand", "문제 분석", f"{data['category_label']} · 긴급도 {data['urgency']}", out.source, error=out.error)],
    }


def route_after_understand(state: AgentState) -> str:
    u = state["understanding"]
    if u["intent"] == "complaint":
        return "plan"
    if u["intent"] == "service":
        return "svc_plan"
    # 민원이 아닌 말은 Claude와 바로 대화하듯 답한다. 위기 표현·다른 창구는 정해진 안내 그대로
    if u["intent"] in ("unclear", "not_complaint") and not state["safety"].get("crisis"):
        return "chat"
    return "end"


def chat(state: AgentState) -> dict:
    """민원이 아닌 첫 메시지(인사·잡담·사용법 질문·불분명한 말): 앞 대화를 기억해 자연스럽게 답한다. 민원 처리로는 가지 않는다."""
    _started("chat")
    u = state["understanding"]
    message = state.get("latest") or state["user_input"]
    history = state.get("chat_history", [])
    result = conversation.small_talk(u["language"], history, message, u["intent"], fallback=u["reply"])
    detail = f"앞 대화 {len(history) // 2}번을 기억해 답함" if history else "대화로 답함"
    if result["guarded"]:
        detail += " · 확인되지 않은 연락처가 있어 정해진 안내로 바꿈"
    return {
        "understanding": {**u, "reply": result["reply"]},
        "chat_history": [*history, {"role": "user", "text": message}, {"role": "agent", "text": result["reply"]}][-12:],
        "chat": {"turns": len(history) // 2 + 1, "guarded": result["guarded"]},
        "log": [_log("chat", "대화", detail, result["source"], error=result["error"])],
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
               ("deliver", "결과물 만들기", "검증한 민원 패키지를 PDF 파일로 만듭니다."))
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
        "language": _language(state),
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
        "language": _language(state),
    }
    out = get_brain().call("check", ctx)
    result = out.value.model_dump()
    if not ctx["can_ask"]:
        result["questions"] = []
    result["questions"] = [q for q in result["questions"] if q["slot"] not in ctx["asked"]][:3]

    # 사진 촬영 위치(GPS)로 이미 확정한 위치는 다시 묻지 않는다
    photo_location = state.get("location") if (state.get("location") or {}).get("from_photo") else None
    if photo_location:
        result["facts"] = [f for f in result["facts"] if f["slot"] != "location"]
        result["facts"].insert(0, {"slot": "location", "value": f"{photo_location['address']} 부근 (사진 촬영 위치)"})
        result["questions"] = [q for q in result["questions"] if q["slot"] != "location"]
        result["location_query"] = photo_location["address"]

    # 이름 없는 장소('창원 초등학교', '우리 아파트')는 위치가 확인된 것으로 보지 않고 한 번 더 묻는다
    # 외국어로 말한 장소는 한국어로 옮긴 지도 검색어로 판단한다
    lang = _language(state)
    fact_location = next((f["value"] for f in result["facts"] if f["slot"] == "location"), "")
    location_text = (fact_location or result["location_query"]) if lang == "ko" else (result["location_query"] or fact_location)
    vague = not photo_location and bool(location_text) and not regions.is_specific_place(location_text)
    if vague and ctx["can_ask"] and "location" not in ctx["asked"] and "location" in ctx["required_info"]:
        question = {"slot": "location", "text": i18n.t("location.vague", lang, place=fact_location or location_text)}
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
    if (state.get("location") or {}).get("from_photo"):
        return "act"  # 사진 촬영 위치로 이미 확정 → 지도 검색 없이 바로 관할 기관 검색
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


def _is_service(state: AgentState) -> bool:
    return (state.get("understanding") or {}).get("intent") == "service"


def route_after_locate(state: AgentState) -> str:
    if state["location"].get("ambiguous") and state.get("confirm_rounds", 0) < MAX_CONFIRM_ROUNDS:
        return "confirm_location"
    return "svc_act" if _is_service(state) else "act"


def confirm_location(state: AgentState) -> dict:
    """Memory·Feedback: 위치 후보를 보여 주고 사용자가 고른 곳으로 확정한다 (모르면 새 장소 표현으로 다시 검색)."""
    candidates = state["location"]["candidates"]
    query = state.get("location_query", "")
    options = [{"value": str(i + 1), "label": f"{c['name'] or c['address']} · {c['address']}"} for i, c in enumerate(candidates)]
    question = {"slot": "location", "text": i18n.t("location.choose", _language(state), query=query, count=len(candidates))}
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
    if not state.get("location_confirmed"):
        return "locate"
    return "svc_act" if _is_service(state) else "act"


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
        "language": _language(state),
    }
    out = get_brain().call("write", ctx)
    package = out.value.model_dump() | {"version": (previous or {}).get("version", 0) + 1}
    # 수정 요청에 대한 답(무엇을 고쳤는지·반영하지 않은 이유). 검증 의견으로 다시 쓸 때는 앞서 한 답을 그대로 둔다
    reply = package["reply"].strip() if revision else (previous or {}).get("reply", "") if review_issues else ""
    guarded = bool(reply and conversation.unknown_contacts(reply, state))
    package["reply"] = "" if guarded else reply

    if revision:
        title, detail = "초안 다시 작성 (사용자 수정 요청)", f"요청: {revision}"
        if guarded:
            detail += " · 답에 확인되지 않은 연락처가 있어 정해진 문장으로 바꿈"
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
    fact_terms = [w for w in fact_loc.split()[:2] if i18n.detect(w) == "ko"]  # 외국어로 말한 장소는 한국어 초안에 그대로 나오지 않는다
    terms = [loc.get("place_name"), loc.get("dong"), loc.get("legal_dong"), *(loc.get("sigungu", "").split()[-1:]), *fact_terms]
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
    if state["review"]["retry"]:
        return "draft"
    return "deliver" if _language(state) == "ko" else "translate"


def translate(state: AgentState) -> dict:
    """시민이 외국인이면 검증을 마친 한국어 민원 패키지를 시민의 언어로 옮긴다 (제출용 원문은 한국어 그대로)."""
    _started("translate")
    lang = _language(state)
    pkg, decision = state["package"], state["decision"]
    review = state.get("review") or {}
    source = {
        "title": pkg["title"], "body": pkg["body"],
        "evidence": [{k: e[k] for k in ("item", "why", "basis")} for e in pkg["evidence"]],
        "tips": pkg["tips"], "reason": decision["reason"], "steps": decision["steps"], "cautions": decision["cautions"],
        "issues": [] if review.get("passed", True) else review.get("issues", []),
        "unit": decision["agency"]["unit"], "duty": decision["agency"]["duty"], "period": decision["period"],
    }
    out = get_brain().call("translate", {"language": lang, "language_name": i18n.LANG_NAMES.get(lang, lang), "source": source})
    result = out.value.model_dump()
    # 목록 개수가 원문과 다르면 어느 항목의 번역인지 알 수 없으니 그 목록만 원문으로 둔다
    mismatched = [k for k in ("evidence", "tips", "steps", "cautions", "issues") if len(result[k]) != len(source[k])]
    for key in mismatched:
        result[key] = source[key]
    translated = out.source == "llm"
    detail = f"{i18n.LANG_NAMES.get(lang, lang)}로 번역 (제출용 원문은 한국어 그대로)" if translated else "번역 실패 → 한국어로 표시"
    if mismatched:
        detail += f" · 개수가 맞지 않아 원문 유지: {', '.join(mismatched)}"
    return {"translation": {**result, "language": lang, "version": pkg["version"], "translated": translated},
            "log": [_log("translate", "번역", detail, out.source, error=out.error)]}


def deliver(state: AgentState) -> dict:
    """Tool Use: 검증을 마친 민원 패키지를 PDF로 만든다."""
    _started("deliver")
    calls: list[dict] = []
    pdf = _run_tool("deliver", calls, "export_pdf", state["package"]["title"], export_pdf, dict(state))["data"]
    return {"files": {"pdf": pdf}, "tool_calls": calls, "log": _tool_logs("deliver", calls)}


def route_entry(state: AgentState) -> str:
    return "draft" if state.get("revision_request") and state.get("package") else "guard"


def route_after_ask(state: AgentState) -> str:
    return "svc_check" if _is_service(state) else "check"


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


# ── 민원 서비스 안내 (서류 발급·신고·신청): 계획 → 필요한 정보 ⇄ 질문 → 위치 → Tool → 안내 ──

def _service(state: AgentState) -> dict:
    return knowledge.service(state["understanding"]["service"])


def svc_plan(state: AgentState) -> dict:
    """Planning: 서비스 템플릿(필요한 정보·찾아갈 기관·무인민원발급기)으로 처리 계획을 세운다."""
    _started("svc_plan")
    u, s, lang = state["understanding"], _service(state), _language(state)

    def step(action: str, key: str = "", **values) -> dict:
        return {"action": action, "title": i18n.t(key or f"svc.step.{action}", lang, **values), "reason": ""}

    steps = [step("service_kb")]
    if not _known_place(state, s["search_at"]):  # 앞 질문에서 확정한 위치가 있으면 묻거나 다시 찾지 않는다
        steps += [step("ask_user", f"svc.step.ask.{need}") for need in s["needs"]]
        steps.append(step("geocode"))
    steps += [step("find_offices", office=i18n.office(kind, lang, knowledge.office_kind(kind)["label"])) for kind in s["offices"]]
    if s["kiosk"]:
        steps.append(step("find_kiosks"))
    steps += [step("check_hours"), step("guide")]
    plan = {"goal": i18n.t("svc.goal", lang, label=u["title"] or s["label"]), "steps": steps,
            "required_info": list(s["needs"]), "fixes": [], "service": u["service"]}
    detail = " → ".join(x["title"] for x in steps)
    return {"plan": plan, "log": [_log("svc_plan", "안내 계획 수립", f"{s['label']} 템플릿: {detail}")]}


def _known_place(state: AgentState, search_at: str) -> str:
    """앞 질문에서 이미 확정한 위치 (같은 용도로 찾은 곳일 때만)."""
    loc = state.get("location") or {}
    return loc.get("address", "") if state.get("location_confirmed") and loc.get("for") == search_at else ""


def svc_check(state: AgentState) -> dict:
    """Reasoning: 가까운 기관을 찾을 위치·주민등록 주소지가 있는지 보고, 없으면 질문을 만든다."""
    _started("svc_check")
    s, lang = _service(state), _language(state)
    rounds = state.get("rounds", 0)
    asked = state.get("asked", [])
    known = _known_place(state, s["search_at"])
    ctx = {
        "service": {"code": state["understanding"]["service"], "label": s["label"], "needs": s["needs"], "search_at": s["search_at"]},
        "dialogue": state["dialogue"], "asked": asked, "can_ask": rounds < settings.max_question_rounds,
        "known_location": known, "language": lang,
        "fallback_questions": {slot: i18n.t(f"svc.ask.{slot}", lang) for slot in ("here", "residence")},
    }
    out = get_brain().call("service_check", ctx)
    r = out.value.model_dump()
    found = {"here": r["here"].strip(), "residence": r["residence"].strip()}
    if known:
        found[s["search_at"]] = known
    questions = [q for q in r["questions"] if q["slot"] in s["needs"] and q["slot"] not in asked and not found.get(q["slot"])]
    if ctx["can_ask"]:
        for need in s["needs"]:  # 꼭 필요한데 비었으면 정해 둔 질문으로라도 묻는다
            if not found.get(need) and need not in asked and all(q["slot"] != need for q in questions):
                questions.append({"slot": need, "text": ctx["fallback_questions"][need]})
    else:
        questions = []

    target = found.get(s["search_at"], "")
    query = known or r["location_query"].strip() or target
    vague = bool(target) and not known and not regions.is_specific_place(f"{target} {query}")
    if vague and ctx["can_ask"] and f"{s['search_at']}_vague" not in asked:
        questions = [{"slot": s["search_at"], "text": i18n.t("svc.ask.vague", lang, place=target)},
                     *[q for q in questions if q["slot"] != s["search_at"]]]
    facts = [{"slot": slot, "value": value} for slot, value in found.items() if value]
    if r["detail"].strip():
        facts.append({"slot": "detail", "value": r["detail"].strip()})
    info = {"facts": facts, "questions": questions[:2], "location_query": "" if questions else query,
            "unknown": [n for n in s["needs"] if not found.get(n)], "location_vague": vague}
    if info["questions"]:
        detail = "질문 필요: " + ", ".join(q["slot"] for q in info["questions"])
    elif known:
        detail = f"앞에서 확인한 위치로 진행: {known}"
    elif query:
        detail = f"필요한 정보 충분 (위치 검색어: {query})"
    else:
        detail = "위치를 알 수 없어 온라인 방법 위주로 안내"
    update = {"info": info, "log": [_log("svc_check", "필요한 정보 판단", detail, out.source, error=out.error)]}
    if vague and info["questions"]:
        update["asked"] = [*asked, f"{s['search_at']}_vague"]  # 모호한 위치는 한 번만 다시 묻는다
    return update


def route_after_svc_check(state: AgentState) -> str:
    if state["info"]["questions"]:
        return "ask"
    if _known_place(state, _service(state)["search_at"]) or not state["info"]["location_query"]:
        return "svc_act"  # 이미 확정한 위치가 있거나, 위치를 끝내 모르면 지도 검색 없이 진행
    return "locate"


def svc_act(state: AgentState) -> dict:
    """Tool Use: 받는 방법 조회 → 가까운 기관·무인민원발급기 찾기 → 지금 운영 여부 확인."""
    _started("svc_act")
    code = state["understanding"]["service"]
    s = knowledge.service(code)
    location = state.get("location") or {}
    calls: list[dict] = []

    def run(tool: str, input_text: str, fn, *args) -> dict:
        return _run_tool("svc_act", calls, tool, input_text, fn, *args)

    kb = run("service_kb", s["label"], offices.service_lookup, code)["data"]
    where = location.get("address") or "(위치 모름)"
    found = {kind: run(f"find_offices:{kind}", where, offices.find_offices, kind, location)["data"] for kind in s["offices"]}
    kiosks = run("find_kiosks", where, offices.find_kiosks, location)["data"] if s["kiosk"] else []
    now = offices.now_info(offices.current_time())
    checked = run("check_hours", offices.now_label(now), offices.check_hours, found, kiosks, now)["data"]

    guide = {**kb, "offices": checked["offices"], "kiosks": checked["kiosks"], "now": now,
             "location": {k: location.get(k, "") for k in ("address", "place_name", "sigungu", "dong")} if location.get("address") else None}
    update = {"guide": guide, "tool_calls": calls, "log": _tool_logs("svc_act", calls)}
    if location.get("address") and not location.get("for"):
        update["location"] = location | {"for": s["search_at"]}  # 이어서 묻는 말에서도 같은 위치를 쓸 수 있게
    return update


def _brief(places: list[dict], limit: int) -> list[dict]:
    return [{"name": p["name"], "distance_m": p.get("distance_m"), "state": p["state"], "today": p["today"],
             "spot": p.get("spot", "")} for p in places[:limit]]


def _unknown_contacts(guide: dict, text: str) -> list[str]:
    """안내 문장에 지식베이스·검색 결과에 없는 전화번호·인터넷 주소가 있으면 돌려준다."""
    phones = {conversation._digits(c["phone"]) for c in guide["channels"] if c.get("phone")}
    hosts = {conversation._host(c["url"]) for c in guide["channels"] if c.get("url")}
    phones |= {conversation._digits(p["phone"]) for places in [*guide["offices"].values(), guide["kiosks"]] for p in places if p.get("phone")}
    bad = []
    for m in conversation.CONTACT.finditer(text):
        token = m.group(0)
        known = conversation._host(token) in hosts if token.lower().startswith(("http", "www")) else conversation._digits(token) in phones
        if not known:
            bad.append(token)
    return bad


def svc_answer(state: AgentState) -> dict:
    """Reasoning: Tool 결과로 지금 가장 좋은 방법·할 일을 시민의 언어로 정리한다 (지어낸 연락처는 막는다)."""
    _started("svc_answer")
    g, lang = state["guide"], _language(state)
    facts = {f["slot"]: f["value"] for f in (state.get("info") or {}).get("facts", [])}
    ctx = {
        "question": state.get("latest") or state["user_input"], "detail": facts.get("detail", ""),
        "service": {k: g[k] for k in ("label", "summary", "deadline", "channels", "prepare", "cautions")},
        "now": g["now"], "location": g["location"],
        "offices": [p | {"kind": knowledge.office_kind(kind)["label"]} for kind, places in g["offices"].items() for p in _brief(places, 2)],
        "kiosks": _brief(g["kiosks"], 3),
        "language": lang, "language_name": i18n.LANG_NAMES.get(lang, lang),
    }
    out = get_brain().call("service_guide", ctx)
    text, source, error = out.value.model_dump(), out.source, out.error
    bad = _unknown_contacts(g, " ".join([text["summary"], text["recommendation"], *text["steps"], *text["tips"]]))
    if bad:  # 확인되지 않은 전화번호·주소를 쓴 안내는 내보내지 않고 정해 둔 문장으로
        text = get_brain().rule.service_guide(ctx).model_dump()
        source, error = "rule_fallback", f"확인되지 않은 연락처 {len(bad)}개 → 정해 둔 안내로 바꿈"
    guide = g | text | {"language": lang, "guarded": bool(bad)}
    return {"guide": guide, "log": [_log("svc_answer", "안내 정리", f"{text['summary']} / 추천: {text['recommendation']}", source, error=error)]}
