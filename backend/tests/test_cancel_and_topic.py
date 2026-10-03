"""중단 버튼(처리 멈추고 그 메시지 전으로 되돌리기)과 대화 중 다른 종류의 민원으로 바꾸기."""

import pytest

from minwon.agent import brain as brain_module
from minwon.agent import cancel
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import TopicCheck
from minwon.tools import kakao
from tests import fake_kakao
from tests.test_agent_flow import client, ended_nodes, new_session, send

ANSWER = "창원시 마산회원구 합성동 합성초등학교 정문 앞이고 평일 등하교 시간에 그래요"


class StopDuring:
    """규칙 엔진에 위임하다가, 정한 단계에서 사용자가 중단 버튼을 누른 것처럼 동작한다."""

    def __init__(self, task: str):
        self.rule = RuleBrain()
        self.task = task

    def __getattr__(self, name):
        if name != self.task:
            return getattr(self.rule, name)

        def press_stop(*_args):
            cancel.request(cancel.current())
            cancel.check()

        return press_stop


class SaysNewTopic(RuleBrain):
    """주제 판단만 정해 둔 답을 돌려주는 가짜 AI."""

    def __init__(self, category: str):
        super().__init__()
        self.category = category

    def switch(self, ctx):
        return TopicCheck(kind="new_complaint", category=self.category, reason="다른 불편을 새로 말함")


def _use(monkeypatch, primary):
    brain = brain_module.Brain(primary)
    monkeypatch.setattr("minwon.agent.nodes.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.topic.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.conversation.get_brain", lambda: brain)


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}").json()


# ---- 중단 ----

def test_cancel_registry_kills_running_process():
    class Proc:
        killed = False

        def kill(self):
            self.killed = True

    proc = Proc()
    cancel.begin("s1")
    with cancel.scope("s1"), cancel.running(proc):
        assert cancel.request("s1") and proc.killed
        with pytest.raises(cancel.Cancelled):
            cancel.check()
    cancel.finish("s1")
    assert not cancel.requested("s1") and not cancel.request("s1")  # 처리 중이 아니면 멈출 것도 없음


def test_cancel_endpoint_when_idle_and_unknown_session():
    sid = new_session()
    assert client.post(f"/api/sessions/{sid}/cancel").json() == {"stopping": False}
    assert client.post("/api/sessions/nope/cancel").status_code == 404


def test_stop_during_first_message_returns_to_empty_conversation(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, StopDuring("plan"))
    sid = new_session()
    events = send(sid, "학교 앞 횡단보도가 너무 위험해요.")
    assert events[-1]["type"] == "cancelled" and events[-1]["restored"] == "new"
    assert ended_nodes(events) == ["guard", "understand"]  # 계획 세우는 중에 멈춤
    assert _state(sid)["status"] == "new"

    _use(monkeypatch, None)
    events = send(sid, "학교 앞 횡단보도가 너무 위험해요.")
    assert events[-1]["type"] == "ask"
    assert sum(d["role"] == "user" for d in _state(sid)["dialogue"]) == 1  # 멈춘 메시지는 대화에 남지 않음


def test_stop_while_answering_goes_back_to_the_question(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    sid = new_session()
    questions = send(sid, "학교 앞 횡단보도가 너무 위험해요.")[-1]["questions"]

    _use(monkeypatch, StopDuring("decide"))
    events = send(sid, ANSWER)
    assert events[-1]["type"] == "cancelled" and events[-1]["restored"] == "asking"
    state = _state(sid)
    assert state["status"] == "asking" and state["pending"]["questions"] == questions

    _use(monkeypatch, None)
    events = send(sid, ANSWER)
    assert events[-1]["type"] == "ready"
    users = [d["text"] for d in _state(sid)["dialogue"] if d["role"] == "user"]
    assert users == ["학교 앞 횡단보도가 너무 위험해요.", ANSWER]  # 멈춘 답변이 두 번 들어가지 않음


def test_stop_during_revision_keeps_the_finished_package(monkeypatch: pytest.MonkeyPatch):
    sid = new_session()
    send(sid, "창원시 성산구 상남동 상가 공사 소음이 매일 아침 7시부터 심해요")
    first = send(sid, "모름")[-1]["package"]

    _use(monkeypatch, StopDuring("write"))
    events = send(sid, "더 짧게 써 주세요")
    assert events[-1]["type"] == "cancelled" and events[-1]["restored"] == "ready"
    state = _state(sid)
    assert state["status"] == "ready" and state["package"]["version"] == first["version"]


# ---- 다른 종류의 민원으로 바꾸기 ----

def test_new_complaint_while_answering_switches_topic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    sid = new_session()
    assert send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")[-1]["type"] == "ask"

    events = send(sid, "그리고 우리 아파트 앞 놀이터 그네가 부서져서 아이들이 다칠 것 같아요")
    changed = events[0]
    assert changed["type"] == "topic_changed"
    assert changed["from"] == "가로등·보안등 고장" and changed["to"] == "공원·놀이터 시설" and changed["source"] == "rule"
    assert ended_nodes(events)[:2] == ["guard", "understand"]  # 새 민원으로 처음부터
    state = _state(sid)
    assert state["understanding"]["category"] == "park_facility"
    assert [d["text"] for d in state["dialogue"] if d["role"] == "user"][0].startswith("그리고 우리 아파트")


def test_new_complaint_after_package_is_not_treated_as_revision():
    sid = new_session()
    send(sid, "창원시 성산구 상남동 상가 공사 소음이 매일 아침 7시부터 심해요")
    assert send(sid, "모름")[-1]["type"] == "ready"

    events = send(sid, "이번엔 집 앞 골목에 쓰레기 무단투기가 너무 심해요")
    assert events[0]["type"] == "topic_changed" and events[0]["to"] == "쓰레기 무단투기·수거"
    assert "draft" not in ended_nodes(events)[:1]  # 수정 요청(초안 다시 쓰기)이 아니라 새 민원으로 시작
    assert _state(sid)["understanding"]["category"] == "garbage"


def test_answers_and_revisions_do_not_switch_topic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    sid = new_session()
    send(sid, "새벽마다 옆 공사장 소음 때문에 잠을 못 자요.")
    events = send(sid, "상가 앞 주차장 옆 공사장이에요")  # '주차'가 들어 있어도 위치 답변
    assert all(e["type"] != "topic_changed" for e in events)
    assert _state(sid)["understanding"]["category"] == "noise"


def test_ai_topic_judgment_is_used_and_same_category_is_ignored(monkeypatch: pytest.MonkeyPatch):
    sid = new_session()
    send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")
    _use(monkeypatch, SaysNewTopic("street_light"))  # AI가 '새 민원'이라 해도 같은 유형이면 그대로 진행
    assert all(e["type"] != "topic_changed" for e in send(sid, "창원시 마산회원구 합성동 골목이에요"))

    sid = new_session()
    send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")
    _use(monkeypatch, SaysNewTopic("animal"))
    events = send(sid, "길에 다친 고양이가 쓰러져 있어요 어떻게 해야 하나요")
    assert events[0]["type"] == "topic_changed" and events[0]["to"] == "동물 관련" and events[0]["source"] == "llm"


def test_stop_after_topic_switch_restores_the_previous_complaint(monkeypatch: pytest.MonkeyPatch):
    sid = new_session()
    questions = send(sid, "우리 골목 가로등이 일주일째 꺼져 있어요.")[-1]["questions"]
    _use(monkeypatch, StopDuring("plan"))
    events = send(sid, "그리고 우리 아파트 앞 놀이터 그네가 부서져서 아이들이 다칠 것 같아요")
    assert events[0]["type"] == "topic_changed" and events[-1]["type"] == "cancelled"
    state = _state(sid)
    assert state["status"] == "asking" and state["pending"]["questions"] == questions
    assert state["understanding"]["category"] == "street_light"
