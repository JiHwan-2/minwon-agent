"""Claude와 바로 대화하는 부분: 민원이 아닌 첫 메시지(인사·잡담·사용법 질문·불분명한 말)와 진행 중인 민원에 대한 질문.

민원 처리(계획·위치·기관·초안)는 워크플로가 맡고, 여기서는 말로만 답한다.
자유 대화는 연락처를 기억으로 지어낼 수 있으므로, 답에 확인되지 않은 전화번호·인터넷 주소가 있으면 내보내지 않고 정해진 문장으로 바꾼다.
"""

import re

from minwon import i18n, knowledge
from minwon.agent.brain import get_brain

CONTACT = re.compile(
    r"(?<!\d)(?:0\d{1,2}[-\s.)]?\d{3,4}[-\s.]?\d{4}|1\d{3}-\d{4})(?!\d)"  # 지역번호 전화·1588-0000 같은 대표번호
    r"|https?://[^\s)\]>\"'，。]+|www\.[^\s)\]>\"'，。]+"
)
HISTORY = 8  # 기억하는 최근 대화 수


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _host(url: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url).split("/")[0].lower().rstrip(".,")


def known_contacts(values: dict | None = None) -> tuple[set[str], set[str]]:
    """답에 써도 되는 연락처 (전화번호 숫자, 인터넷 주소 호스트): 지식베이스 창구·다른 창구, 이번 민원에서 찾은 기관."""
    phones, hosts = set(), set()
    entries = [*knowledge.all_channels().values(), *knowledge.referrals().values()]
    values = values or {}
    entries += (values.get("agencies") or {}).get("departments", []) + (values.get("agencies") or {}).get("channels", [])
    decision = values.get("decision") or {}
    entries += [decision.get("agency") or {}, decision.get("channel") or {}]
    for found in (values.get("nearby") or {}).values():
        entries += found
    for e in entries:
        if e.get("phone"):
            phones.add(_digits(e["phone"]))
        if e.get("url"):
            hosts.add(_host(e["url"]))
    return phones, hosts


def unknown_contacts(text: str, values: dict | None = None) -> list[str]:
    phones, hosts = known_contacts(values)
    bad = []
    for m in CONTACT.finditer(text):
        token = m.group(0)
        known = _host(token) in hosts if token.lower().startswith(("http", "www")) else _digits(token) in phones
        if not known:
            bad.append(token)
    return bad


def _call(ctx: dict, fallback: str, values: dict | None = None) -> dict:
    out = get_brain().call("chat", ctx | {"fallback": fallback})
    reply = out.value.reply.strip() or fallback
    bad = unknown_contacts(reply, values)
    return {"reply": fallback if bad else reply, "source": out.source, "error": out.error, "guarded": bool(bad)}


def small_talk(language: str, history: list[dict], message: str, intent: str, fallback: str) -> dict:
    """민원이 아닌 말에 앞 대화를 기억해 자연스럽게 답한다. fallback은 Claude가 실패하거나 연락처를 지어냈을 때 보낼 문장."""
    ctx = {
        "mode": "small_talk", "language": language, "language_name": i18n.LANG_NAMES.get(language, language),
        "intent": intent, "history": history[-HISTORY:], "message": message,
    }
    return _call(ctx, fallback)


def _context(values: dict) -> dict:
    """진행 중인 민원에서 답의 근거로 쓸 수 있는 정보만 모은다."""
    u = values.get("understanding") or {}
    plan = values.get("plan") or {}
    info = values.get("info") or {}
    loc = values.get("location") or {}
    decision = values.get("decision") or {}
    pkg = values.get("package") or {}
    review = values.get("review") or {}
    slots = knowledge.slots()
    ctx = {
        "민원": {k: u.get(k) for k in ("title", "summary", "category_label")},
        "처리 계획": {"goal": plan.get("goal"), "steps": [f"{s['title']}: {s['reason']}" for s in plan.get("steps", [])],
                   "필수 정보": [slots[s]["label"] for s in plan.get("required_info", []) if s in slots]},
        "확인된 정보": [f"{slots.get(f['slot'], {}).get('label', f['slot'])}: {f['value']}" for f in info.get("facts", [])],
    }
    if loc.get("address"):
        ctx["확인된 위치"] = {k: loc.get(k) for k in ("place_name", "address", "sigungu", "dong")}
    if decision:
        ctx["담당 기관 판단"] = {
            "기관": {k: decision["agency"].get(k) for k in ("agency", "unit", "duty", "phone")},
            "제출 창구": {k: decision["channel"].get(k) for k in ("name", "url", "phone", "use")},
            "처리 기간": decision.get("period"), "판단 이유": decision.get("reason"),
            "할 일": decision.get("steps"), "주의": decision.get("cautions"),
        }
    if pkg:
        ctx["민원 초안"] = {"제목": pkg.get("title"), "본문": pkg.get("body"),
                         "증빙": [{k: e.get(k) for k in ("item", "level", "why", "basis")} for e in pkg.get("evidence", [])],
                         "팁": pkg.get("tips")}
        ctx["검증"] = {"통과": review.get("passed"), "남은 문제": review.get("issues", [])}
    return ctx


def answer(values: dict, pending: dict | None, message: str) -> dict:
    """진행 중인 민원에 대한 질문에, 지금까지 확인된 정보만 근거로 답한다 (그래프는 진행하지 않음)."""
    language = (values.get("understanding") or {}).get("language", "ko")
    ctx = {
        "mode": "question", "language": language, "language_name": i18n.LANG_NAMES.get(language, language),
        "stage": "asking" if pending else "ready",
        "pending_questions": [q["text"] for q in (pending or {}).get("questions", [])],
        "history": [{"role": d["role"], "text": d["text"]} for d in values.get("dialogue", [])][-HISTORY:],
        "message": message,
        "context": _context(values),
    }
    return _call(ctx, i18n.t("answer.fallback", language), values)
