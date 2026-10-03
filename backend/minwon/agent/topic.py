"""대화 도중(질문에 답하는 중이거나 민원이 완성된 뒤) 들어온 말이 지금 민원에 이어지는지,
다른 종류의 새 민원인지, 관계없는 말인지 판단한다."""

import re

from minwon import knowledge
from minwon.agent.brain import get_brain

# 질문에 답하는 중의 '모름'·'네'·'1번' 같은 짧은 답은 판단하지 않고 그대로 답변으로 받는다 (불필요한 AI 호출 방지).
# 완성 후에는 짧은 말도 판단한다. 잘못 받으면 초안을 통째로 다시 쓰게 되기 때문이다.
SHORT_REPLY = re.compile(r"^\s*(\d+\s*번?|네|예|응|아니요|아니오|모름|몰라요?|모르겠어요|없음|없어요)\s*[.!]?\s*$")

# 관계없는 말에는 그래프를 진행하지 않고 정해진 안내(i18n의 off_topic.*)만 한다 (질문 횟수·대화 기록·초안은 그대로)


def worth_checking(text: str, stage: str) -> bool:
    return stage == "ready" or not SHORT_REPLY.match(text)


def detect(values: dict, pending: dict | None, text: str) -> dict | None:
    """지금 민원에 이어지는 말이면 None.
    다른 종류의 새 민원이면 {kind: new_complaint, from, to, ...}, 관계없는 말이면 {kind: off_topic, ...}."""
    understanding = values.get("understanding")
    if not understanding:
        return None
    ctx = {
        "current": {k: understanding[k] for k in ("category", "category_label", "title", "summary")},
        "stage": "asking" if pending else "ready",
        "pending_questions": [q["text"] for q in (pending or {}).get("questions", [])],
        "message": text,
    }
    out = get_brain().call("switch", ctx)
    check = out.value
    meta = {"reason": check.reason, "source": out.source, "error": out.error}
    if check.kind in ("off_topic", "question"):
        return {"kind": check.kind, **meta}
    if check.kind != "new_complaint" or check.category == understanding["category"]:
        return None
    return {
        "kind": "new_complaint",
        "from": understanding["category_label"],
        "to": knowledge.category(check.category)["label"],
        "from_category": understanding["category"],
        "to_category": check.category,
        **meta,
    }
