"""민원이 아니거나 불분명한 입력은 민원 흐름을 시작하지 않고 안내한다.
대화 도중(질문에 답하는 중·완성 후)의 관계없는 말은 진행하지 않고 그대로 둔다."""

import pytest

from minwon import i18n, knowledge
from minwon.agent import brain as brain_module
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import ReferralCode, TopicCheck
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


class JudgesTurn(RuleBrain):
    """대화 도중 말만 정해 둔 대로 판단하는 가짜 Claude: 정한 낱말이 있으면 관계없는 말 (나머지는 규칙 엔진)."""

    def __init__(self, off_topic_words: list[str]):
        super().__init__()
        self.words = off_topic_words
        self.checked: list[str] = []

    def switch(self, ctx):
        self.checked.append(ctx["message"])
        if any(w in ctx["message"] for w in self.words):
            return TopicCheck(kind="off_topic", category=ctx["current"]["category"], reason="지금 민원과 관계없는 말")
        return super().switch(ctx)


class FailsToJudgeTurn(RuleBrain):
    def switch(self, ctx):
        raise TimeoutError("Claude 응답 없음")


class RefersTo(RuleBrain):
    """정한 낱말이 있으면 '다른 창구가 맞는 일'로 판단하는 가짜 Claude. 답 문장에는 일부러 틀린 번호를 넣는다."""

    def __init__(self, codes: dict[str, str]):
        super().__init__()
        self.codes = codes
        self.seen: list[str] = []

    def understand(self, text):
        self.seen.append(text)
        base = super().understand(text)
        code = next((v for k, v in self.codes.items() if k in text), None)
        if code is None:
            return base
        return base.model_copy(update={"intent": "referral", "referral": code, "reply": "0000-0000으로 전화하세요", "category": "other"})


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
    assert last == {"type": "redirect", "intent": "not_complaint", "message": REPLY["not_complaint"], "referral": None}
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


# ---- 대화 도중의 관계없는 말 ----

NOISE = "창원시 성산구 상남동 상가 공사 소음이 매일 아침 7시부터 심해요"


def test_off_topic_answer_keeps_the_same_questions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    fake = _use(monkeypatch, JudgesTurn(["기모띠"]))
    sid = new_session()
    asked = send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")[-1]
    before = _state(sid)

    events = send(sid, "기모띠")
    assert ended_nodes(events) == []  # 답변으로 처리하지 않음
    last = events[-1]
    assert last["type"] == "off_topic" and last["stage"] == "asking" and last["questions"] == asked["questions"]
    after = _state(sid)
    assert after["status"] == "asking" and after["pending"] == before["pending"]
    assert after["dialogue"] == before["dialogue"]  # 대화 기록·질문 횟수 그대로
    assert fake.checked == ["기모띠"]

    events = send(sid, "창원시 마산회원구 합성동 합성초등학교 정문 앞이고 밤마다 그래요")
    assert events[-1]["type"] != "off_topic" and "check" in ended_nodes(events)


def test_off_topic_after_package_keeps_the_draft(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, JudgesTurn(["기모띠", "감사"]))
    sid = new_session()
    send(sid, NOISE)
    first = send(sid, "모름")[-1]
    assert first["type"] == "ready"

    for text in ("기모띠", "감사합니다"):
        events = send(sid, text)
        assert ended_nodes(events) == []  # 초안을 다시 쓰지 않음
        assert events[-1]["type"] == "off_topic" and events[-1]["stage"] == "ready" and events[-1]["questions"] == []
    assert _state(sid)["package"] == first["package"]

    events = send(sid, "더 짧게 써 주세요")
    assert events[-1]["type"] == "ready" and events[-1]["package"]["version"] > first["package"]["version"]


def test_short_answers_are_checked_only_after_the_package(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, JudgesTurn([]))
    sid = new_session()
    send(sid, NOISE)
    send(sid, "모름")  # 질문에 대한 짧은 답은 판단 없이 바로 답변으로
    assert fake.checked == []
    send(sid, "네")  # 완성 후에는 짧은 말도 판단 (잘못 받으면 초안을 통째로 다시 씀)
    assert fake.checked == ["네"]


def test_when_claude_fails_mid_conversation_the_message_is_an_answer(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, FailsToJudgeTurn())
    sid = new_session()
    send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")
    events = send(sid, "기모띠")
    assert events[-1]["type"] != "off_topic" and "check" in ended_nodes(events)


# ---- 위기 표현 ----

CRISIS = "요즘 너무 힘들어서 죽고 싶어요"


def test_crisis_gets_fixed_109_notice_and_no_complaint_example(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, JudgesIntent({"죽고": "not_complaint"}))
    sid = new_session()
    events = send(sid, CRISIS)
    assert events[0] == {"type": "crisis", "message": i18n.t("crisis.notice", "ko")}  # AI 판단보다 먼저
    assert "109" in events[0]["message"]
    assert events[-1]["type"] == "redirect" and events[-1]["message"] == i18n.t("crisis.reply.new", "ko")  # Claude 답 대신 정해진 문장
    assert _state(sid)["safety"]["crisis"] is True
    assert "위기 표현" in _state(sid)["log"][0]["detail"]


def test_crisis_notice_does_not_depend_on_claude(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, FailsToUnderstand())
    events = send(new_session(), CRISIS)
    assert events[0]["type"] == "crisis"


def test_complaint_with_crisis_words_gets_notice_and_continues():
    events = send(new_session(), "윗집 층간소음 때문에 매일 밤 잠을 못 자서 죽고 싶을 지경이에요")
    assert events[0]["type"] == "crisis"
    assert "plan" in ended_nodes(events)  # 민원 흐름은 그대로 진행


def test_crisis_while_answering_pauses_without_reasking(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, JudgesTurn(["죽고"]))
    sid = new_session()
    send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")
    before = _state(sid)
    events = send(sid, CRISIS)
    assert [e["type"] for e in events] == ["crisis", "off_topic"]
    last = events[-1]
    assert last["crisis"] and last["message"] == i18n.t("crisis.reply.paused", "ko") and last["questions"] == []
    assert _state(sid)["pending"] == before["pending"]  # 하던 민원은 그대로


# ---- 다른 창구가 맞는 일 (소비자 피해·임금체불·사기·개인 간 분쟁) ----

def test_referral_channels_are_complete_in_knowledge_base():
    codes = set(ReferralCode.__args__) - {"none"}
    assert set(knowledge.referrals()) == codes
    for ref in knowledge.referrals().values():
        assert all(ref[k] for k in ("label", "examples", "agency", "phone", "url", "first", "source"))
        assert ref["url"].startswith("https://")


def test_referral_uses_official_channel_not_claude_words(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, RefersTo({"택배": "consumer"}))
    sid = new_session()
    events = send(sid, "택배가 3일째 안 와요")
    assert ended_nodes(events) == ["guard", "understand"]  # 민원 흐름을 시작하지 않음
    last = events[-1]
    assert last["type"] == "redirect" and last["intent"] == "referral"
    assert last["referral"]["code"] == "consumer" and last["referral"]["phone"] == "1372"
    assert last["referral"]["url"] == "https://www.ccn.go.kr"
    assert "1372 소비자상담센터" in last["message"] and "0000-0000" not in last["message"]  # Claude가 쓴 번호는 쓰지 않음
    log = _state(sid)["log"][-1]
    assert log["title"] == "입력 확인" and "1372 소비자상담센터 안내" in log["detail"]


def test_referral_then_real_complaint_starts_fresh(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, RefersTo({"월급": "labor"}))
    sid = new_session()
    assert send(sid, "사장님이 두 달째 월급을 안 줘요")[-1]["referral"]["phone"] == "1350"
    events = send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요")
    assert fake.seen[-1] == "우리 골목 가로등이 일주일째 꺼져 있어요"  # 앞의 말과 합치지 않음
    assert "plan" in ended_nodes(events)


def test_referral_without_a_channel_falls_back_to_complaint(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, RefersTo({"가로등": "none"}))
    sid = new_session()
    events = send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요")
    assert "plan" in ended_nodes(events)
    assert _state(sid)["understanding"]["intent"] == "complaint"
