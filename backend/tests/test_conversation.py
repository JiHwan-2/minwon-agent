"""Claude와 바로 대화하는 부분: 민원이 아닌 말은 앞 대화를 기억해 답하고, 진행 중인 민원에 대한 질문에는 확인된 정보로 답한다.
어느 쪽이든 지어낸 연락처는 내보내지 않는다."""

import pytest

from minwon import i18n
from minwon.agent import brain as brain_module
from minwon.agent import conversation
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import ChatReply, TopicCheck
from minwon.tools import kakao
from tests import fake_kakao
from tests.test_agent_flow import client, ended_nodes, new_session, send

NOISE = "창원시 성산구 상남동 상가 공사 소음이 매일 아침 7시부터 심해요"
FORM_REPLY = "양식에서 받은 안내 문장"


class Chats(RuleBrain):
    """민원 여부·대화 도중 판단·대화 답만 정해 둔 가짜 Claude (나머지는 규칙 엔진)."""

    def __init__(self, small_talk=(), questions=(), reply=None):
        super().__init__()
        self.small_talk, self.questions, self.reply = small_talk, questions, reply
        self.chats: list[dict] = []

    def understand(self, text):
        base = super().understand(text)
        if any(w in text.splitlines()[-1] for w in self.small_talk):
            return base.model_copy(update={"intent": "not_complaint", "reply": FORM_REPLY, "category": "other"})
        return base

    def switch(self, ctx):
        if any(w in ctx["message"] for w in self.questions):
            return TopicCheck(kind="question", category=ctx["current"]["category"], reason="진행 중 민원에 대한 질문")
        return super().switch(ctx)

    def chat(self, ctx):
        self.chats.append(ctx)
        return ChatReply(reply=self.reply or f"{ctx['mode']} 답 (앞 대화 {len(ctx['history'])}줄)")


class FailsToChat(Chats):
    def chat(self, ctx):
        raise TimeoutError("Claude 응답 없음")


def _use(monkeypatch, primary):
    brain = brain_module.Brain(primary)
    monkeypatch.setattr("minwon.agent.nodes.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.topic.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.conversation.get_brain", lambda: brain)
    return primary


def _state(sid):
    return client.get(f"/api/sessions/{sid}").json()


# ---- 민원이 아닌 첫 메시지 ----

def test_small_talk_is_answered_with_memory_then_real_complaint_starts(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, Chats(small_talk=("안녕", "뭘 할 수")))
    sid = new_session()
    events = send(sid, "안녕하세요")
    assert ended_nodes(events) == ["guard", "understand", "chat"]  # 민원 처리로 가지 않음
    assert events[-1]["message"] == "small_talk 답 (앞 대화 0줄)"

    events = send(sid, "너는 뭘 할 수 있어?")
    assert events[-1]["message"] == "small_talk 답 (앞 대화 2줄)"  # 앞 대화를 기억함
    assert fake.chats[-1]["history"][0] == {"role": "user", "text": "안녕하세요"}
    assert fake.chats[-1]["message"] == "너는 뭘 할 수 있어?"

    events = send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요")
    assert "plan" in ended_nodes(events) and "chat" not in ended_nodes(events)


def test_made_up_contact_is_not_sent(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, Chats(small_talk=("전화번호",), reply="창원시청 대표번호는 055-225-2114예요."))
    sid = new_session()
    events = send(sid, "창원시청 전화번호 알려 줘")
    assert events[-1]["message"] == FORM_REPLY  # 지어낸 번호 대신 정해 둔 안내
    assert "연락처" in _state(sid)["log"][-1]["detail"]


def test_chat_failure_falls_back_to_form_reply(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, FailsToChat(small_talk=("안녕",)))
    sid = new_session()
    assert send(sid, "안녕")[-1]["message"] == FORM_REPLY
    assert _state(sid)["log"][-1]["source"] == "rule_fallback"


def test_crisis_is_not_handed_to_chat(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, Chats(small_talk=("죽고",)))
    events = send(new_session(), "요즘 너무 힘들어서 죽고 싶어요")
    assert ended_nodes(events) == ["guard", "understand"]  # 위기 표현은 정해진 문장 그대로
    assert events[-1]["message"] == i18n.t("crisis.reply.new", "ko") and not fake.chats


# ---- 진행 중인 민원에 대한 질문 ----

def test_question_while_answering_is_answered_and_questions_shown_again(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    fake = _use(monkeypatch, Chats(questions=("왜 그걸",)))
    sid = new_session()
    asked = send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")[-1]
    before = _state(sid)

    events = send(sid, "왜 그걸 물어봐요?")
    assert ended_nodes(events) == []  # 그래프를 진행하지 않음
    last = events[-1]
    assert last["type"] == "answer" and last["stage"] == "asking" and last["questions"] == asked["questions"]
    assert last["message"] == "question 답 (앞 대화 1줄)"
    assert _state(sid)["pending"] == before["pending"] and _state(sid)["dialogue"] == before["dialogue"]
    ctx = fake.chats[-1]
    assert ctx["stage"] == "asking" and ctx["pending_questions"] == [q["text"] for q in asked["questions"]]
    assert "민원" in ctx["context"] and "담당 기관 판단" not in ctx["context"]  # 아직 정해지지 않은 정보는 주지 않음


def test_question_after_package_uses_result_and_keeps_draft(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, Chats(questions=("얼마나",)))
    sid = new_session()
    send(sid, NOISE)
    first = send(sid, "모름")[-1]
    events = send(sid, "처리는 얼마나 걸려요?")
    assert events[-1]["type"] == "answer" and events[-1]["stage"] == "ready" and ended_nodes(events) == []
    assert _state(sid)["package"] == first["package"]  # 초안을 다시 쓰지 않음
    assert fake.chats[-1]["context"]["담당 기관 판단"]["처리 기간"] == first["decision"]["period"]


def test_answer_with_unknown_contact_is_replaced(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, Chats(questions=("얼마나",), reply="자세한 건 http://fake-office.example.com 에서 보세요."))
    sid = new_session()
    send(sid, NOISE)
    send(sid, "모름")
    last = send(sid, "처리는 얼마나 걸려요?")[-1]
    assert last["message"] == i18n.t("answer.fallback", "ko") and last["guarded"]


def test_contact_check_allows_only_known_contacts():
    assert conversation.unknown_contacts("국민신문고(https://www.epeople.go.kr)나 110으로 물어보세요") == []
    assert conversation.unknown_contacts("1372 소비자상담센터(www.ccn.go.kr)") == []
    assert conversation.unknown_contacts("창원시청 대표번호는 055-225-2114예요") == ["055-225-2114"]
    assert conversation.unknown_contacts("담당자 휴대폰 010-1234-5678") == ["010-1234-5678"]
    found = {"decision": {"agency": {"agency": "상남동 행정복지센터", "phone": "055-272-5300"}, "channel": {}}}
    assert conversation.unknown_contacts("상남동 행정복지센터(055-272-5300)에 문의하세요", found) == []  # 이번 민원에서 찾은 번호는 허용
