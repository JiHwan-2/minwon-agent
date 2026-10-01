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
    location: dict                                    # geocode 결과 (candidates·ambiguous 포함)
    location_query: str                               # 위치 확인에 쓸 검색어 (후보 확인 단계에서 바뀔 수 있음)
    location_confirmed: bool                          # 사용자가 후보를 고르거나 구체적인 위치로 확정했는지
    confirm_rounds: int                               # 위치 후보 확인 질문 횟수
    nearby: dict                                      # 종류별 주변 기관
    agencies: dict                                    # 담당 부서·창구·절차·증빙
    tool_calls: Annotated[list[dict], operator.add]   # Tool 호출 기록
    decision: dict                                    # 주 담당 기관·제출 창구·할 일
    package: dict                                     # 민원 초안·증빙 체크리스트 (최신본)
    review: dict                                      # 최근 검증 결과
    review_rounds: int                                # 이번 작성 주기의 검증 횟수
    revision_request: str                             # 완성 후 사용자의 수정 요청
    log: Annotated[list[dict], operator.add]          # 실행 로그
