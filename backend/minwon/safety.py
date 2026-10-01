"""입력 안전장치: 개인정보 마스킹, 긴급상황 감지, 지시 주입 시도 감지."""

import re
from dataclasses import dataclass, field

# 한글 조사가 숫자 바로 뒤에 붙으므로(예: 010-1234-5678이고) \b 대신 숫자 경계를 쓴다.
PII_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("rrn", "주민등록번호", re.compile(r"(?<!\d)\d{6}\s*-\s*[1-8]\d{6}(?!\d)")),
    ("card", "카드번호", re.compile(r"(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)")),
    ("mobile", "휴대전화번호", re.compile(r"(?<!\d)01[016789][\s-]?\d{3,4}[\s-]?\d{4}(?!\d)")),
    ("phone", "전화번호", re.compile(r"(?<!\d)0(?:2|[3-6][1-5]|70)[\s-]?\d{3,4}[\s-]?\d{4}(?!\d)")),
    ("email", "이메일", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
]

EMERGENCY_PATTERNS = re.compile(
    r"(불이 ?났|화재|연기가 ?(?:나|많이)|쓰러졌|의식이 ?없|피를 ?많이|숨을 ?안|가스 ?냄새|폭발|"
    r"칼을|흉기|폭행|맞고 ?있|납치|물에 ?빠졌|지금 ?무너|붕괴)"
)

INJECTION_PATTERNS = re.compile(
    r"(이전\s*(?:지시|명령|규칙).{0,6}무시|시스템\s*프롬프트|프롬프트를?\s*(?:보여|출력|알려)|"
    r"너의?\s*(?:규칙|지시사항)|ignore\s+(?:all\s+|the\s+)?(?:previous|above)\s+instructions|system\s+prompt)",
    re.IGNORECASE,
)


@dataclass
class MaskResult:
    text: str
    findings: list[dict] = field(default_factory=list)


def mask_pii(text: str) -> MaskResult:
    findings = []
    for kind, label, pattern in PII_PATTERNS:
        text, count = pattern.subn(f"[{label} 가림]", text)
        if count:
            findings.append({"kind": kind, "label": label, "count": count})
    return MaskResult(text=text, findings=findings)


def is_emergency(text: str) -> bool:
    return bool(EMERGENCY_PATTERNS.search(text))


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text))
