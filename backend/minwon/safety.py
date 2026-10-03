"""입력 안전장치: 개인정보 마스킹, 긴급상황·위기 표현 감지, 지시 주입 시도 감지."""

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
    r"칼을|흉기|폭행|맞고 ?있|납치|물에 ?빠졌|지금 ?무너|붕괴|"
    # 번역해 둔 외국어 (영어·베트남어·중국어·태국어·인도네시아어·우즈베크어·일본어)
    r"\bon fire\b|\bhouse fire\b|\bfire (?:broke out|in)\b|\bunconscious\b|\bgas leak|\bexplosion\b|\bstabbed\b|\bbeing attacked\b|\bkidnapp|"
    r"đang cháy|cháy nhà|bất tỉnh|rò rỉ (?:gas|khí)|phát nổ|vụ nổ|bị đâm|bắt cóc|"
    r"着火|失火|火灾|昏迷|晕倒|煤气泄漏|燃气泄漏|爆炸|被刺|绑架|"
    r"ไฟไหม้|หมดสติ|แก๊สรั่ว|ระเบิด|ถูกแทง|ลักพาตัว|"
    r"kebakaran|pingsan|tidak sadarkan diri|kebocoran gas|ledakan|ditusuk|penculikan|"
    r"yong'in|hushidan ketdi|gaz siz|portla|pichoqla|o'g'irlab ket|"
    r"火事|火災|意識がない|ガス漏れ|爆発|刺され|誘拐)",
    re.IGNORECASE,
)

# 스스로를 해치려는 위기 표현. 놓치는 것보다 한 번 더 안내하는 편이 나으므로 넓게 잡는다.
# '짜증나 죽겠어요'처럼 흔한 과장 표현(죽겠다)은 넣지 않는다.
CRISIS_PATTERNS = re.compile(
    r"(죽고\s*싶|자살|목숨을?\s*끊|스스로\s*목숨|살기\s*싫|살고\s*싶지\s*않|사라지고\s*싶|극단적\s*(?:인\s*)?선택|"
    r"뛰어내리고\s*싶|자해|삶을\s*끝내|"
    # 번역해 둔 외국어
    r"\bwant to die\b|\bkill myself\b|\bsuicid|\bend my life\b|\bdon'?t want to live\b|\bhurt myself\b|"
    r"muốn chết|tự tử|tự sát|không muốn sống|"
    r"想死|自杀|轻生|不想活|"
    r"อยากตาย|ฆ่าตัวตาย|"
    r"ingin mati|mau mati|bunuh diri|tidak ingin hidup|"
    r"o'lgim kel|o'zimni o'ldir|joniga qasd|yashagim kelmay|"
    r"死にたい|自殺|消えたい|生きていたくない)",
    re.IGNORECASE,
)

# 위기 표현이 있으면 AI 판단과 관계없이 정해진 문장(i18n의 crisis.*)으로 안내한다.
# 자살예방 상담전화 109: 보건복지부가 1393·1577-0199·1388 등을 2024-01-01부터 통합한 24시간 번호

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


def is_crisis(text: str) -> bool:
    return bool(CRISIS_PATTERNS.search(text))


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text))
