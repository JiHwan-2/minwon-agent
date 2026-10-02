export const NODE_LABEL = {
  guard: "입력 안전 점검",
  understand: "문제 분석",
  plan: "처리 계획",
  check: "정보 판단",
  ask: "추가 질문",
  locate: "위치 확인",
  confirm_location: "위치 후보 확인",
  act: "Tool 실행",
  decide: "담당 기관 판단",
  draft: "민원 초안 작성",
  review: "초안 검증",
  deliver: "결과물 만들기",
  switch: "민원 종류 변경",
  stop: "처리 중단",
  off_topic: "입력 확인",
};

export const TOOL_SOURCE_LABEL = {
  kakao: "카카오 API",
  text_fallback: "대체 경로",
  kb: "지식베이스",
  "kb+region": "지식베이스+지역",
  data_go_kr: "공공데이터 API",
  generated: "파일 생성",
  skipped: "건너뜀",
  error: "실패",
};

export const ACTION_LABEL = {
  ask_user: "질문",
  geocode: "위치 확인",
  find_nearby: "주변 기관",
  kb_lookup: "부서·절차",
  case_search: "사례 조회",
  write: "초안 작성",
  review: "검증",
  deliver: "결과물",
};

export const SLOT_LABEL = {
  location: "발생 위치",
  time: "발생 시간대",
  frequency: "반복 빈도",
  detail: "구체적 상황",
  harm: "위험·피해",
  target: "원인 대상",
};

export const URGENCY_LABEL = { high: "긴급", medium: "보통", low: "낮음" };

export const SOURCE_LABEL = {
  llm: "AI 판단",
  rule: "규칙 엔진",
  rule_fallback: "대체 경로",
  system: "시스템",
  tool: "Tool",
};

export const EXAMPLES = [
  "학교 앞 횡단보도가 너무 위험해요.",
  "우리 골목 가로등이 일주일째 꺼져 있어요.",
  "새벽마다 옆 공사장 소음 때문에 잠을 못 자요.",
  "아파트 앞 인도에 차들이 매일 주차해서 유모차가 못 지나가요.",
];
