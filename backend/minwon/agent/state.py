import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    user_input: str                                   # 개인정보를 가린 첫 입력
    pii_findings: list[dict]                          # API 경계에서 가린 개인정보 종류·건수
    safety: dict                                      # 긴급상황·지시주입 판단
    understanding: dict                               # 유형·요약·긴급도
    plan: dict                                        # 처리 계획 (화면 표시용)
    dialogue: Annotated[list[dict], operator.add]     # 질문·답변 기록 (Memory)
    info: dict                                        # 확인된 정보·질문·위치 검색어
    asked: list[str]                                  # 이미 질문한 항목
    rounds: int                                       # 추가 질문 횟수
    location: dict                                    # geocode 결과
    nearby: dict                                      # 종류별 주변 기관
    agencies: dict                                    # 담당 부서·창구·절차·증빙
    tool_calls: Annotated[list[dict], operator.add]   # Tool 호출 기록
    log: Annotated[list[dict], operator.add]          # 실행 로그
