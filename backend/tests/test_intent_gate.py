"""민원이 아니거나 불분명한 입력은 민원 흐름을 시작하지 않고 안내한다."""

import pytest

from minwon.agent import brain as brain_module
from minwon.agent.rules import RuleBrain
from minwon.tools import kakao
from tests import fake_kakao
from tests.test_agent_flow import client, ended_nodes, new_session, send

REPLY = {
    "not_complaint": "저는 생활 속 불편을 민원으로 정리해 드리는 도우미예요. 불편했던 일을 말씀해 주세요.",
    "unclear": "어떤 점이 불편하신지 조금만 더 알려 주세요.",
}


class JudgesIntent(RuleBrain):
    """민원 여부만 정해 둔 대로 판단하는 가짜 Claude (나머지 단계는 규칙 엔진)."""

    def __init__(self, intents: dict[str, str]):
        super().__init__()
        self.intents = intents
        self.seen: list[str] = []

    def understand(self, text):
        self.seen.append(text)
        base = super().understand(text)
        latest = text.splitlines()[-1]  # 합쳐진 입력이면 새로 말한 줄에 불편이 드러나는지로 판단
        intent = next((v for k, v in self.intents.items() if k in latest), "complaint")
        if intent == "complaint":
            return base
        return base.model_copy(update={"intent": intent, "reply": REPLY[intent], "category": "other"})


class FailsToUnderstand(RuleBrain):
    def understand(self, text):
        raise TimeoutError("Claude 응답 없음")


def _use(monkeypatch, primary):
    brain = brain_module.Brain(primary)
    monkeypatch.setattr("minwon.agent.nodes.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.topic.get_brain", lambda: brain)
    return primary


def _state(sid):
    return client.get(f"/api/sessions/{sid}").json()


def test_not_a_complaint_is_answered_without_starting_the_flow(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, JudgesIntent({"기모띠": "not_complaint"}))
    sid = new_session()
    events = send(sid, "기모띠")
    assert ended_nodes(events) == ["guard", "understand"]
    last = events[-1]
    assert last == {"type": "redirect", "intent": "not_complaint", "message": REPLY["not_complaint"]}
    log = _state(sid)["log"]
    assert log[-1]["title"] == "입력 확인" and "민원이 아닌 입력" in log[-1]["detail"]
    assert _state(sid)["plan"] is None


def test_real_complaint_after_small_talk_starts_fresh(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    fake = _use(monkeypatch, JudgesIntent({"기모띠": "not_complaint"}))
    sid = new_session()
    send(sid, "기모띠")
    events = send(sid, "창원 합성초등학교 앞 횡단보도가 평일 아침마다 위험해요")
    assert "plan" in ended_nodes(events)
    assert fake.seen[-1] == "창원 합성초등학교 앞 횡단보도가 평일 아침마다 위험해요"
    assert events[-1]["type"] == "ready"


def test_unclear_input_is_combined_with_the_next_message(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, JudgesIntent({"짜증": "unclear"}))
    sid = new_session()
    first = send(sid, "아 진짜 짜증나요")
    assert first[-1]["type"] == "redirect" and first[-1]["intent"] == "unclear"

    events = send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요")
    assert fake.seen[-1] == "아 진짜 짜증나요\n우리 골목 가로등이 일주일째 꺼져 있어요"
    assert "plan" in ended_nodes(events)
    assert _state(sid)["understanding"]["category"] == "street_light"


def test_unclear_twice_keeps_asking(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, JudgesIntent({"짜증": "unclear", "해결": "unclear"}))
    sid = new_session()
    send(sid, "짜증나요")
    events = send(sid, "그냥 해결해 주세요")
    assert events[-1]["type"] == "redirect" and events[-1]["intent"] == "unclear"


def test_emergency_is_never_turned_away(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, JudgesIntent({"불이": "not_complaint"}))
    events = send(new_session(), "지금 골목에서 불이 났어요")
    assert events[-1]["type"] != "redirect"
    assert "plan" in ended_nodes(events)


def test_when_claude_fails_the_input_is_treated_as_a_complaint(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, FailsToUnderstand())
    sid = new_session()
    events = send(sid, "기모띠")
    assert "plan" in ended_nodes(events)
    understand_log = next(e for e in _state(sid)["log"] if e["node"] == "understand")
    assert understand_log["source"] == "rule_fallback" and "TimeoutError" in understand_log["error"]
