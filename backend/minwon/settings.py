import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _csv(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "rule").lower()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
    anthropic_effort: str = os.getenv("ANTHROPIC_EFFORT", "medium")
    anthropic_effort_fast: str = os.getenv("ANTHROPIC_EFFORT_FAST", "low")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")
    kakao_rest_api_key: str = os.getenv("KAKAO_REST_API_KEY", "")
    max_question_rounds: int = int(os.getenv("MAX_QUESTION_ROUNDS", "2"))
    max_review_rounds: int = int(os.getenv("MAX_REVIEW_ROUNDS", "2"))
    cors_origins: list[str] = field(default_factory=lambda: _csv("CORS_ORIGINS", "http://localhost:5173"))

    @property
    def model_label(self) -> str:
        return {
            "anthropic": self.anthropic_model,
            "openai": self.openai_model,
        }.get(self.llm_provider, "규칙 기반")


settings = Settings()
