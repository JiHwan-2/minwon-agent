"""LLM이 각 단계에서 반환해야 하는 구조 (모든 필드 필수: JSON Schema 구조화 출력으로 강제)."""

from typing import Literal

from pydantic import BaseModel, Field

CategoryCode = Literal[
    "traffic_safety", "illegal_parking", "road_damage", "street_light", "noise", "garbage",
    "pollution", "park_facility", "animal", "public_transport", "water_sewer", "other",
]
Slot = Literal["location", "time", "frequency", "detail", "harm", "target"]
Action = Literal["ask_user", "geocode", "find_nearby", "kb_lookup", "case_search", "write", "review", "deliver"]
NearbyKind = Literal["police", "community_center"]


Intent = Literal["complaint", "service", "referral", "unclear", "not_complaint"]
ReferralCode = Literal["none", "consumer", "labor", "crime", "legal"]  # knowledge/agencies.json의 referrals
ServiceCode = Literal[  # knowledge/services.json의 services
    "none", "resident_copy", "family_cert", "seal_cert", "land_building", "car_registry", "passport", "local_tax_cert",
    "national_tax_cert", "health_insurance", "driving_record", "military_cert", "graduation_cert", "move_in", "id_card",
    "birth_report", "bulky_waste", "welfare",
]


class Understanding(BaseModel):
    intent: Intent = Field(
        description="complaint=도와줄 생활불편이 하나라도 있음, "
        "service=서류 발급·신고·신청 같은 민원 서비스를 어디서·어떻게·얼마에 하는지 물음(등본·가족관계증명서·여권·전입신고 등), "
        "referral=시·군·구청 민원이 아니라 다른 공식 창구가 해결하는 일(소비자 피해·임금체불·사기·개인 간 분쟁), "
        "unclear=불편이 있는 듯하지만 무엇이 불편한지 알 수 없음, "
        "not_complaint=생활불편·민원과 관계없는 말(인사·잡담·의미 없는 말·유행어·장난·다른 주제 질문)"
    )
    service: ServiceCode = Field(description="intent가 service면 맞는 민원 서비스 코드, 아니면 none")
    referral: ReferralCode = Field(description="intent가 referral이면 맞는 창구 코드, 아니면 none")
    language: str = Field(description="시민 입력의 언어 코드: ko, en, zh, vi 중 하나 (그 밖의 언어면 en)")
    reply: str = Field(
        description="intent가 unclear·not_complaint면 시민에게 보낼 안내 1~2문장(시민의 언어로, 친절하게, 생활불편 예시 하나 포함). "
        "complaint·referral이면 빈 문자열"
    )
    category: CategoryCode = Field(description="생활불편 유형 코드 (민원이 아니면 other)")
    title: str = Field(description="불편을 한 줄로 요약한 제목, 25자 이내, 시민의 언어로")
    summary: str = Field(description="무엇이 어디서 어떻게 불편한지 2문장 이내로 정리, 시민의 언어로. 입력에 없는 사실은 쓰지 않는다")
    urgency: Literal["low", "medium", "high"] = Field(description="사람이 다칠 위험이 있으면 high")
    keywords: list[str] = Field(description="핵심 단어 2~5개. 공공데이터 검색에 쓰므로 시민의 언어와 상관없이 항상 한국어 단어")
    location_hint: str = Field(description="입력에 나온 장소 표현 그대로. 없으면 빈 문자열")


class PlanStep(BaseModel):
    action: Action = Field(
        description="ask_user=부족한 정보 질문, geocode=위치를 주소·행정구역으로 확인, "
        "find_nearby=주변 공공기관 검색, kb_lookup=담당 부서·절차 조회, case_search=비슷한 민원 사례 조회(공공데이터), "
        "write=민원 초안 작성, review=초안 검증, deliver=민원 패키지 PDF 만들기"
    )
    title: str = Field(description="사용자에게 보여줄 단계 이름, 15자 이내")
    reason: str = Field(description="이 단계가 필요한 이유 한 문장")


class Plan(BaseModel):
    goal: str = Field(description="이번 민원 처리의 목표 한 문장")
    steps: list[PlanStep] = Field(description="실행 순서대로 4~7단계")
    required_info: list[Slot] = Field(description="민원 처리에 꼭 필요한 정보 항목")
    nearby_kinds: list[NearbyKind] = Field(description="주변에서 찾아야 할 기관 종류. 필요 없으면 빈 목록")


class Fact(BaseModel):
    slot: Slot
    value: str = Field(description="대화에서 사용자가 실제로 말한 내용만. 추측 금지")


class Question(BaseModel):
    slot: Slot
    text: str = Field(description="사용자에게 보낼 쉽고 구체적인 질문 한 문장, 예시 포함")


ChannelId = Literal["safety_report", "epeople", "eco_report", "floor_noise", "police_call", "local_call"]


class Decision(BaseModel):
    primary: int = Field(description="departments 목록에서 주 담당 기관의 번호(0부터)")
    channel_id: ChannelId = Field(description="channels 목록 중 가장 알맞은 제출 창구의 id")
    reason: str = Field(description="이 기관·창구를 고른 이유 1~2문장. 검색 결과와 유형을 근거로 든다")
    steps: list[str] = Field(description="이 시민이 실제로 할 일을 순서대로 3~5개, 상황에 맞게 구체적으로")
    cautions: list[str] = Field(description="제출 전에 알아 둘 점 0~2개 (예: 신호등은 경찰서 심의 필요)")
    relevant_cases: list[int] = Field(description="similar_cases 중 이 민원과 같은 종류의 문제인 사례 번호(0부터). 관련 없으면 빈 목록")


EvidenceLevel = Literal["required", "recommended", "separate"]


class EvidenceItem(BaseModel):
    item: str = Field(description="준비할 증빙자료")
    level: EvidenceLevel = Field(
        description="required=지키지 않으면 처리되지 않는 공식 요건(지식베이스에 required로 있는 것만), "
        "recommended=있으면 처리에 도움, separate=피해 보상 등 민원과 별도 절차에 필요"
    )
    why: str = Field(description="필요한 이유 한 문장")
    basis: str = Field(description="required일 때 근거 제도. 그 외에는 빈 문자열")


class Draft(BaseModel):
    title: str = Field(description="민원 제목, 40자 이내, 장소와 요청이 드러나게")
    body: str = Field(
        description="민원 본문. 인사 → 위치·발생 시기·상황 → 문제점 → 구체적 요청 → 맺음말. "
        "시민이 말하지 않은 사실은 [ ] 빈칸으로 남긴다"
    )
    evidence: list[EvidenceItem] = Field(description="증빙자료 체크리스트 3~6개")
    tips: list[str] = Field(description="제출 전 팁 1~3개")


class Critique(BaseModel):
    passed: bool = Field(description="고칠 점이 없으면 true")
    issues: list[str] = Field(description="고쳐야 할 점. 대화에 없는 사실, 담당 기관과 맞지 않는 요청, 어색한 문장 등. 없으면 빈 목록")


class InfoCheck(BaseModel):
    facts: list[Fact] = Field(description="지금까지 확인된 정보")
    questions: list[Question] = Field(description="아직 모르는 필수 정보에 대한 질문, 최대 3개. 충분하면 빈 목록")
    location_query: str = Field(description="지도 검색에 넣을 위치 문자열(시·구·동 + 장소명). 모르면 빈 문자열")


class ChatReply(BaseModel):
    reply: str = Field(description="시민에게 보낼 답 2~4문장, language 언어로")


class EvidenceText(BaseModel):
    item: str
    why: str
    basis: str


class Translation(BaseModel):
    """한국어로 쓴 민원 패키지를 시민의 언어로 옮긴 것 (화면 표시용. 제출용 원문은 한국어 그대로)."""
    title: str
    body: str = Field(description="줄바꿈·■ 소제목·[ ] 빈칸 구조를 원문과 똑같이 유지")
    evidence: list[EvidenceText] = Field(description="원문 evidence와 같은 개수·순서")
    tips: list[str] = Field(description="원문 tips와 같은 개수·순서")
    reason: str
    steps: list[str] = Field(description="원문 steps와 같은 개수·순서")
    cautions: list[str] = Field(description="원문 cautions와 같은 개수·순서")
    issues: list[str] = Field(description="원문 issues와 같은 개수·순서")
    unit: str
    duty: str
    period: str


ServiceSlot = Literal["here", "residence"]


class ServiceQuestion(BaseModel):
    slot: ServiceSlot
    text: str = Field(description="시민에게 보낼 쉽고 구체적인 질문 한 문장, 예시 포함, 시민의 언어로")


class ServiceCheck(BaseModel):
    """민원 서비스 안내에 필요한 정보: 가까운 기관을 찾을 위치와 주민등록 주소지."""
    here: str = Field(description="시민이 말한 지금 있는 곳이나 찾아갈 동네 (말한 그대로). 없으면 빈 문자열")
    residence: str = Field(description="시민이 말한 주민등록 주소지(이사했으면 새 주소). 없으면 빈 문자열")
    detail: str = Field(description="안내에 필요한 세부 사항 (서류 종류·용도·분실 여부 등) 한 문장. 없으면 빈 문자열")
    questions: list[ServiceQuestion] = Field(description="needs 중 아직 모르는 것만 질문, 최대 2개. can_ask가 false면 빈 목록")
    location_query: str = Field(description="search_at 위치를 지도에서 찾을 검색어(시·구·동 + 장소명), 한국어. 모르면 빈 문자열")


class ServiceGuide(BaseModel):
    """민원 서비스 안내: 받는 방법·기관·운영 여부를 근거로 시민에게 지금 가장 좋은 방법을 알려 준다."""
    summary: str = Field(description="시민의 질문에 대한 바로 답 1~2문장, 시민의 언어로")
    recommendation: str = Field(description="지금 시각·운영 여부·거리를 따져 가장 좋은 방법과 이유 1~2문장, 시민의 언어로")
    steps: list[str] = Field(description="시민이 할 일 3~5개, 순서대로, 시민의 언어로")
    tips: list[str] = Field(description="이 시민의 상황에서 알아 둘 점 0~3개, 시민의 언어로")


class PhotoAnalysis(BaseModel):
    """시민이 올린 현장 사진에서 찾은 생활불편과, 맞는지 '예/아니요'로 확인할 질문."""
    relevant: bool = Field(description="도로·보도·골목·공원 등 공공장소가 찍혀 있어 불편을 짐작할 수 있으면 true. 공공장소가 전혀 없으면(셀카·음식·물건·문서 등) false")
    scene: str = Field(description="사진에 실제로 보이는 장면 1~2문장, 시민의 언어로")
    issue: str = Field(description="시민이 불편해할 가장 그럴듯한 문제 한 문장, 시민의 언어로. relevant가 false면 빈 문자열")
    question: str = Field(description="issue가 맞는지 예/아니요로 답할 확인 질문 한 문장, 시민의 언어로. relevant가 false면 빈 문자열")
    category: CategoryCode = Field(description="issue의 생활불편 유형 코드 (relevant가 false면 other)")
    emergency: bool = Field(description="불이 났거나 사람이 다쳐 있거나 구조물이 무너지는 중처럼 112·119 신고가 먼저인 상황이면 true")
    location_clues: str = Field(description="사진에 보이는 도로명판·건물 번호판·간판·정류장 이름 등 위치 단서 글자를 보이는 그대로. 없으면 빈 문자열")


class PhotoAnswer(BaseModel):
    answer: Literal["yes", "no", "unclear"] = Field(description="시민의 답이 확인 질문에 대한 긍정이면 yes, 부정이거나 다른 문제를 말하면 no, 알 수 없으면 unclear")
    issue: str = Field(description="시민이 답 속에서 직접 말한 불편이나 보충 설명 (시민의 말 그대로 정리). 예/아니요만 했으면 빈 문자열")
    reason: str = Field(description="판단 이유 한 문장, 한국어")


TurnKind = Literal["continue", "new_complaint", "question", "off_topic"]


class TopicCheck(BaseModel):
    kind: TurnKind = Field(description="continue=지금 민원에 대한 답변·보충·'모름'·초안 수정 요청, new_complaint=지금 민원과 다른 종류의 생활불편을 새로 말함, question=지금 민원·진행 과정·결과에 대해 묻기만 함(답변·수정 요청 없음), off_topic=답변도 수정 요청도 새 불편도 민원 질문도 아닌 말(의미 없는 말·유행어·인사·감사·맞장구·잡담·다른 주제 질문)")
    category: CategoryCode = Field(description="새 민원이면 그 유형 코드, 아니면 지금 민원의 유형 코드")
    reason: str = Field(description="판단 이유 한 문장")
