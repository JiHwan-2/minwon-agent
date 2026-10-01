"""판단 엔진 선택: LLM(Claude/GPT)을 우선 사용하고, 실패하면 규칙 엔진으로 대체한다."""

import json
import logging
from dataclasses import dataclass
from functools import cache
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from minwon.agent import prompts
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import Critique, Decision, Draft, InfoCheck, Plan, Understanding
from minwon.settings import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMBrain:
    def __init__(self, provider: str):
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            def make(effort: str, max_tokens: int):
                return ChatAnthropic(
                    model=settings.anthropic_model,
                    max_tokens=max_tokens,
                    reasoning_effort=effort,
                    default_request_timeout=90,
                    max_retries=2,
                )

            self.fast = make(settings.anthropic_effort_fast, 8000)
            self.deep = make(settings.anthropic_effort, 16000)
        elif provider == "openai":
            from langchain_openai import ChatOpenAI

            self.fast = self.deep = ChatOpenAI(model=settings.openai_model, temperature=0.2, timeout=90, max_retries=2)
        else:
            raise ValueError(f"지원하지 않는 LLM_PROVIDER: {provider}")

    @staticmethod
    def _ask(model, schema: type[T], system: str, payload: Any) -> T:
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        runnable = model.with_structured_output(schema, method="json_schema")
        return runnable.invoke([SystemMessage(system), HumanMessage(content)])

    def understand(self, text: str) -> Understanding:
        return self._ask(self.fast, Understanding, prompts.UNDERSTAND, f"[시민 입력]\n{text}")

    def plan(self, ctx: dict) -> Plan:
        return self._ask(self.deep, Plan, prompts.PLAN, ctx)

    def check(self, ctx: dict) -> InfoCheck:
        return self._ask(self.fast, InfoCheck, prompts.CHECK, ctx)

    def decide(self, ctx: dict) -> Decision:
        return self._ask(self.deep, Decision, prompts.DECIDE, ctx)

    def write(self, ctx: dict) -> Draft:
        return self._ask(self.deep, Draft, prompts.WRITE, ctx)

    def critique(self, ctx: dict) -> Critique:
        return self._ask(self.fast, Critique, prompts.CRITIQUE, ctx)


@dataclass
class Outcome:
    value: Any
    source: str  # llm | rule | rule_fallback
    error: str = ""


class Brain:
    def __init__(self, primary: LLMBrain | None):
        self.primary = primary
        self.rule = RuleBrain()

    @property
    def mode(self) -> str:
        return "llm" if self.primary else "rule"

    def call(self, task: str, *args) -> Outcome:
        if self.primary:
            try:
                return Outcome(getattr(self.primary, task)(*args), "llm")
            except Exception as e:
                log.warning("LLM %s 실패, 규칙 엔진으로 대체: %s", task, e)
                return Outcome(getattr(self.rule, task)(*args), "rule_fallback", f"{type(e).__name__}: {e}"[:200])
        return Outcome(getattr(self.rule, task)(*args), "rule")


@cache
def get_brain() -> Brain:
    if settings.llm_provider in ("anthropic", "openai"):
        return Brain(LLMBrain(settings.llm_provider))
    return Brain(None)
