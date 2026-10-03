"""판단 엔진 선택: Claude Code(claude -p)를 우선 사용하고, 실패하면 규칙 엔진으로 대체한다."""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from functools import cache
from typing import Any, TypeVar

from pydantic import BaseModel

from minwon.agent import cancel, prompts
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import Critique, Decision, Draft, InfoCheck, Plan, TopicCheck, Translation, Understanding
from minwon.settings import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# 이 변수가 있으면 claude가 API 키로 과금되므로 지우고, 로그인된 Claude 계정을 쓰게 한다.
_DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")


class ClaudeCodeError(RuntimeError):
    pass


class ClaudeCodeBrain:
    """이 PC에 설치·로그인된 Claude Code CLI를 단계마다 한 번씩 실행해 판단한다 (API 키 불필요).

    도구는 모두 끄고(--tools ""), 단계별 지시문으로 기본 지시문을 바꾸고(--system-prompt),
    단계별 출력 구조를 JSON Schema로 강제한다(--json-schema).
    """

    attempts = 2  # Claude 쪽 일시 오류(과부하·로그인 갱신 충돌)면 한 번 더 시도

    def _cmd(self, schema: type[BaseModel], system: str, effort: str) -> list[str]:
        exe = settings.claude_cli or shutil.which("claude")
        if not exe or (settings.claude_cli and not Path(exe).exists()):
            raise ClaudeCodeError("Claude Code(claude)를 찾을 수 없습니다. 설치·로그인 후 다시 실행해 주세요")
        return [
            exe, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema.model_json_schema(), ensure_ascii=False),
            "--system-prompt", system,
            "--tools", "",
            "--model", settings.claude_model,
            "--effort", effort,
            "--no-session-persistence",
            "--safe-mode",  # CLAUDE.md·스킬·훅·MCP를 읽지 않아 지시문 그대로, 더 빨리 실행
            "--strict-mcp-config",
        ]

    def _run(self, cmd: list[str], content: str) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
        cancel.check()
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=tempfile.gettempdir(), env=env,
        )
        with cancel.running(proc):  # 중단을 누르면 이 프로세스를 바로 끝낸다
            try:
                stdout, stderr = proc.communicate(content, timeout=settings.claude_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
        cancel.check()
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            raise ClaudeCodeError(f"응답을 읽을 수 없습니다 (종료 코드 {proc.returncode}): {(stderr or stdout).strip()[:150]}")

    def _ask(self, effort: str, schema: type[T], system: str, payload: Any) -> T:
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        cmd = self._cmd(schema, system, effort)
        for attempt in range(1, self.attempts + 1):
            data = self._run(cmd, content)
            if not data.get("is_error"):
                break
            if attempt == self.attempts:
                raise ClaudeCodeError(str(data.get("result", "알 수 없는 오류"))[:200])
            time.sleep(2)
        value = data.get("structured_output")
        if value is None:
            value = _json_in(data.get("result", ""))
        return schema.model_validate(value)

    def understand(self, text: str) -> Understanding:
        return self._ask(settings.claude_effort_fast, Understanding, prompts.UNDERSTAND, f"[시민 입력]\n{text}")

    def plan(self, ctx: dict) -> Plan:
        return self._ask(settings.claude_effort, Plan, prompts.PLAN, ctx)

    def check(self, ctx: dict) -> InfoCheck:
        return self._ask(settings.claude_effort_fast, InfoCheck, prompts.CHECK, ctx)

    def decide(self, ctx: dict) -> Decision:
        return self._ask(settings.claude_effort, Decision, prompts.DECIDE, ctx)

    def write(self, ctx: dict) -> Draft:
        return self._ask(settings.claude_effort, Draft, prompts.WRITE, ctx)

    def critique(self, ctx: dict) -> Critique:
        return self._ask(settings.claude_effort_fast, Critique, prompts.CRITIQUE, ctx)

    def switch(self, ctx: dict) -> TopicCheck:
        return self._ask(settings.claude_effort_fast, TopicCheck, prompts.SWITCH, ctx)

    def translate(self, ctx: dict) -> Translation:
        return self._ask(settings.claude_effort_fast, Translation, prompts.TRANSLATE, ctx)


def _json_in(text: str) -> Any:
    """구조화 출력이 비어 있을 때 대비: 답변 텍스트에서 JSON 부분만 꺼낸다 (```json 감싸기 허용)."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


@dataclass
class Outcome:
    value: Any
    source: str  # llm | rule | rule_fallback
    error: str = ""


class Brain:
    def __init__(self, primary: ClaudeCodeBrain | None):
        self.primary = primary
        self.rule = RuleBrain()

    @property
    def mode(self) -> str:
        return "llm" if self.primary else "rule"

    def call(self, task: str, *args) -> Outcome:
        if self.primary:
            try:
                return Outcome(getattr(self.primary, task)(*args), "llm")
            except cancel.Cancelled:
                raise  # 중단은 대체 경로로 넘기지 않고 처리 전체를 멈춘다
            except Exception as e:
                log.warning("LLM %s 실패, 규칙 엔진으로 대체: %s", task, e)
                return Outcome(getattr(self.rule, task)(*args), "rule_fallback", f"{type(e).__name__}: {e}"[:200])
        return Outcome(getattr(self.rule, task)(*args), "rule")


@cache
def get_brain() -> Brain:
    if settings.llm_provider == "claude_code":
        return Brain(ClaudeCodeBrain())
    if settings.llm_provider != "rule":
        log.warning("지원하지 않는 LLM_PROVIDER=%s → 규칙 엔진으로 동작 (claude_code | rule)", settings.llm_provider)
    return Brain(None)
