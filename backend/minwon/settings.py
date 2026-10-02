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
    claude_cli: str = os.getenv("CLAUDE_CLI", "")  # 비우면 PATH에서 claude 실행 파일을 찾음
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    claude_effort: str = os.getenv("CLAUDE_EFFORT", "medium")
    claude_effort_fast: str = os.getenv("CLAUDE_EFFORT_FAST", "low")
    claude_timeout: int = int(os.getenv("CLAUDE_TIMEOUT", "120"))
    kakao_rest_api_key: str = os.getenv("KAKAO_REST_API_KEY", "")
    data_go_kr_service_key: str = os.getenv("DATA_GO_KR_SERVICE_KEY", "")
    pdf_font_path: str = os.getenv("PDF_FONT_PATH", "")  # 비우면 운영체제 기본 한글 글꼴(맑은 고딕 등)을 찾음
    pdf_font_bold_path: str = os.getenv("PDF_FONT_BOLD_PATH", "")
    max_question_rounds: int = int(os.getenv("MAX_QUESTION_ROUNDS", "2"))
    max_review_rounds: int = int(os.getenv("MAX_REVIEW_ROUNDS", "2"))
    cors_origins: list[str] = field(default_factory=lambda: _csv("CORS_ORIGINS", "http://localhost:5173"))

    @property
    def model_label(self) -> str:
        if self.llm_provider == "claude_code":
            name = self.claude_model if self.claude_model.startswith("claude") else f"Claude {self.claude_model}"
            return f"{name} (Claude Code)"
        return "규칙 기반"


settings = Settings()
