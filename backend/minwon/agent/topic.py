"""대화 도중 다른 종류의 민원이 들어왔는지 판단한다 (질문에 답하는 중이거나 민원이 완성된 뒤)."""

import re

from minwon import knowledge
from minwon.agent.brain import get_brain

# '모름'·'네'·'1번'처럼 짧은 답은 판단하지 않고 그대로 답변으로 받는다 (불필요한 AI 호출 방지)
SHORT_REPLY = re.compile(r"^\s*(\d+\s*번?|네|예|응|아니요|아니오|모름|몰라요?|모르겠어요|없음|없어요)\s*[.!]?\s*$")


def worth_checking(text: str) -> bool:
    return len(text.strip()) > 6 and not SHORT_REPLY.match(text)


def detect(values: dict, pending: dict | None, text: str) -> dict | None:
    """다른 종류의 새 민원이면 {from, to, reason, source, error}, 아니면 None."""
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
    if not check.new_complaint or check.category == understanding["category"]:
        return None
    return {
        "from": understanding["category_label"],
        "to": knowledge.category(check.category)["label"],
        "reason": check.reason,
        "source": out.source,
        "error": out.error,
    }
