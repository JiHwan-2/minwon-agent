"""Claude Code 판단 엔진: 실제 claude를 실행하지 않고 가짜 응답으로 명령 구성·응답 해석·대체 경로를 확인한다."""

import dataclasses
import json
import subprocess

import pytest

from minwon.agent import brain as brain_module
from minwon.agent.brain import Brain, ClaudeCodeBrain, ClaudeCodeError
from minwon.agent.schemas import Understanding

UNDERSTOOD = {
    "category": "street_light", "title": "골목 가로등 고장", "summary": "골목 가로등이 일주일째 꺼져 있습니다.",
    "urgency": "medium", "keywords": ["가로등", "골목"], "location_hint": "",
}


class FakeClaude:
    """subprocess.run 대신 불려서 받은 명령을 기록하고, 정해 둔 응답을 차례로 돌려준다."""

    def __init__(self, *replies: dict | str):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": cmd, **kwargs})
        reply = self.replies.pop(0)
        stdout = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(brain_module, "settings", dataclasses.replace(brain_module.settings, claude_cli="claude-test"))
    monkeypatch.setattr(brain_module.time, "sleep", lambda _s: None)

    def install(*replies):
        fake = FakeClaude(*replies)
        monkeypatch.setattr(brain_module.subprocess, "run", fake)
        return fake

    return install


def _ok(**extra) -> dict:
    return {"type": "result", "is_error": False, **extra}


def test_builds_command_without_tools_or_api_key(fake_cli, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = fake_cli(_ok(structured_output=UNDERSTOOD))

    result = ClaudeCodeBrain().understand("우리 골목 가로등이 일주일째 꺼져 있어요.")

    assert result == Understanding(**UNDERSTOOD)
    call = fake.calls[0]
    cmd = call["cmd"]
    assert cmd[:2] == ["claude-test", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["title"] == "Understanding"
    assert "판단 엔진" in cmd[cmd.index("--system-prompt") + 1]
    assert "가로등이 일주일째" in call["input"]  # 시민 입력은 명령줄이 아니라 표준입력으로
    assert "ANTHROPIC_API_KEY" not in call["env"]  # API 과금 대신 로그인된 계정 사용


def test_reads_json_from_result_text_when_no_structured_output(fake_cli):
    fake_cli(_ok(result=f"```json\n{json.dumps(UNDERSTOOD, ensure_ascii=False)}\n```"))
    assert ClaudeCodeBrain().understand("가로등 고장").category == "street_light"


def test_retries_once_on_claude_error(fake_cli):
    fake = fake_cli({"is_error": True, "result": "Overloaded"}, _ok(structured_output=UNDERSTOOD))
    assert ClaudeCodeBrain().understand("가로등 고장").title == "골목 가로등 고장"
    assert len(fake.calls) == 2


def test_error_after_retry_falls_back_to_rule_engine(fake_cli):
    fake_cli(*[{"is_error": True, "result": "Failed to refresh OAuth token"}] * 2)
    with pytest.raises(ClaudeCodeError, match="OAuth"):
        ClaudeCodeBrain().understand("가로등 고장")

    fake_cli(*[{"is_error": True, "result": "Failed to refresh OAuth token"}] * 2)
    out = Brain(ClaudeCodeBrain()).call("understand", "우리 골목 가로등이 일주일째 꺼져 있어요.")
    assert out.source == "rule_fallback"
    assert "ClaudeCodeError" in out.error
    assert out.value.category == "street_light"


def test_unreadable_output_is_reported(fake_cli):
    fake_cli("Error: something went wrong")
    with pytest.raises(ClaudeCodeError, match="응답을 읽을 수 없습니다"):
        ClaudeCodeBrain().understand("가로등 고장")


def test_missing_cli_falls_back_with_clear_message(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(brain_module, "settings", dataclasses.replace(brain_module.settings, claude_cli=""))
    monkeypatch.setattr(brain_module.shutil, "which", lambda _name: None)
    out = Brain(ClaudeCodeBrain()).call("understand", "가로등이 꺼졌어요")
    assert out.source == "rule_fallback"
    assert "Claude Code(claude)를 찾을 수 없습니다" in out.error


def test_timeout_falls_back(fake_cli, monkeypatch: pytest.MonkeyPatch):
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(brain_module.subprocess, "run", slow)
    out = Brain(ClaudeCodeBrain()).call("understand", "가로등이 꺼졌어요")
    assert out.source == "rule_fallback"
    assert "TimeoutExpired" in out.error
