"""완성 후 수정 요청: Claude가 다시 쓰면서 시민에게 무엇을 고쳤는지·반영하지 않은 이유를 답한다.
답에 지어낸 연락처가 있으면 내보내지 않고, 검증 의견으로 다시 쓸 때도 앞서 한 답은 그대로 둔다."""

import pytest

from minwon.agent import brain as brain_module
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import Critique
from tests.test_agent_flow import client, ended_nodes, new_session, send

NOISE = "창원시 성산구 상남동 상가 공사 소음이 매일 아침 7시부터 심해요"
REPLY = "전화번호는 본문에 넣지 않았어요. 제출 사이트의 민원인 정보 칸에 적어 주세요."


class Replies(RuleBrain):
    """초안 작성 때 정해 둔 답을 함께 내는 가짜 Claude (나머지는 규칙 엔진). 검토는 수정 후 처음 한 번만 문제를 낼 수 있다."""

    def __init__(self, reply=REPLY, fail_after_revision=False, always=False):
        super().__init__()
        self.reply, self.fail_after_revision, self.always = reply, fail_after_revision, always
        self.writes: list[dict] = []
        self.failed = False

    def write(self, ctx):
        self.writes.append(ctx)
        reply = self.reply if ctx["revision_request"] or self.always else ""
        return super().write(ctx).model_copy(update={"reply": reply})

    def critique(self, ctx):
        revised = any(d.get("kind") == "revision" for d in ctx["dialogue"])
        if self.fail_after_revision and revised and not self.failed:
            self.failed = True
            return Critique(passed=False, issues=["시민이 말하지 않은 표현이 있음"])
        return super().critique(ctx)


def _use(monkeypatch, primary):
    brain = brain_module.Brain(primary)
    monkeypatch.setattr("minwon.agent.nodes.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.topic.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.conversation.get_brain", lambda: brain)
    return primary


def _finish(sid: str) -> dict:
    events = send(sid, NOISE)
    while events[-1]["type"] == "ask":
        events = send(sid, "모름")
    return events[-1]


def test_first_draft_has_no_reply_even_if_claude_writes_one(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, Replies(always=True))
    assert _finish(new_session())["package"]["reply"] == ""  # 수정 요청이 없으면 답하지 않는다


def test_revision_reply_reaches_the_citizen(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, Replies())
    sid = new_session()
    _finish(sid)
    ready = send(sid, "제 전화번호도 본문에 넣어 주세요")[-1]
    assert ready["type"] == "ready" and ready["package"]["reply"] == REPLY
    assert fake.writes[-1]["revision_request"] and fake.writes[-1]["language"] == "ko"


def test_reply_with_unknown_contact_is_not_shown(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, Replies(reply="한국전력 055-123-4567로 전화해 보세요."))
    sid = new_session()
    _finish(sid)
    ready = send(sid, "한국전력에 내고 싶어요")[-1]
    assert ready["package"]["reply"] == ""  # 화면에는 정해진 문장이 나간다
    log = [x for x in client.get(f"/api/sessions/{sid}").json()["log"] if x["node"] == "draft"][-1]
    assert "확인되지 않은 연락처" in log["detail"]


def test_review_rewrite_keeps_the_reply(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, Replies(fail_after_revision=True))
    sid = new_session()
    _finish(sid)
    events = send(sid, "학원 얘기는 빼 주세요")
    assert ended_nodes(events).count("draft") == 2  # 수정 → 검증 의견 → 다시 작성
    assert fake.writes[-1]["revision_request"] == "" and fake.writes[-1]["review_issues"]
    assert events[-1]["package"]["reply"] == REPLY  # 검증 의견으로 다시 쓴 초안에도 수정 요청에 한 답이 남는다
