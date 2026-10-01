"""LLM이 각 단계에서 반환해야 하는 구조 (모든 필드 필수: OpenAI strict 모드 호환)."""

from typing import Literal

from pydantic import BaseModel, Field

CategoryCode = Literal[
    "traffic_safety", "illegal_parking", "road_damage", "street_light", "noise", "garbage",
    "pollution", "park_facility", "animal", "public_transport", "water_sewer", "other",
]
Slot = Literal["location", "time", "frequency", "detail", "harm", "target"]
Action = Literal["ask_user", "geocode", "find_nearby", "kb_lookup", "write", "review"]
NearbyKind = Literal["police", "community_center"]


class Understanding(BaseModel):
    category: CategoryCode = Field(description="생활불편 유형 코드")
    title: str = Field(description="불편을 한 줄로 요약한 제목, 25자 이내")
    summary: str = Field(description="무엇이 어디서 어떻게 불편한지 2문장 이내로 정리. 입력에 없는 사실은 쓰지 않는다")
    urgency: Literal["low", "medium", "high"] = Field(description="사람이 다칠 위험이 있으면 high")
    keywords: list[str] = Field(description="핵심 단어 2~5개")
    location_hint: str = Field(description="입력에 나온 장소 표현 그대로. 없으면 빈 문자열")


class PlanStep(BaseModel):
    action: Action = Field(
        description="ask_user=부족한 정보 질문, geocode=위치를 주소·행정구역으로 확인, "
        "find_nearby=주변 공공기관 검색, kb_lookup=담당 부서·절차 조회, write=민원 초안 작성, review=초안 검증"
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


class InfoCheck(BaseModel):
    facts: list[Fact] = Field(description="지금까지 확인된 정보")
    questions: list[Question] = Field(description="아직 모르는 필수 정보에 대한 질문, 최대 3개. 충분하면 빈 목록")
    location_query: str = Field(description="지도 검색에 넣을 위치 문자열(시·구·동 + 장소명). 모르면 빈 문자열")
