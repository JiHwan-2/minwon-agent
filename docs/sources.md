# 출처 · AI 활용 · 신규개발분 기록표

제출용 「출처/AI 활용 신고서」 작성을 위해 개발 중 계속 누적 기록합니다.

## 개발 경위
- 아이디어와 기획은 참가 신청서(2026-09-18 제출)의 개발 계획서를 따릅니다.

## AI 도구
| 도구 | 용도 | 비고 |
|---|---|---|
| Claude Code (Anthropic) | 코드 작성 보조, 설계 문서 초안 | 팀이 검토·수정 후 커밋 |
| Claude API (Anthropic) | 서비스 내 LLM (분석·계획·판단·생성·검토) | |
| OpenAI API (선택) | 서비스 내 LLM 대체 옵션 | |

## 오픈소스
| 이름 | 용도 | 라이선스 |
|---|---|---|
| LangGraph | Agent 상태 그래프, 추가 질문 일시정지(interrupt), 세션 상태 저장 | MIT |
| LangChain (langchain-core, langchain-anthropic, langchain-openai) | Claude/GPT 호출, 구조화 출력 | MIT |
| FastAPI / Uvicorn | API 서버 | MIT / BSD-3-Clause |
| Pydantic | 입출력 스키마 검증 | MIT |
| python-dotenv, httpx | 설정 로드, HTTP 호출 | BSD-3-Clause |
| pytest | 자동 테스트 | MIT |
| React / React DOM | 화면 | MIT |
| Vite, @vitejs/plugin-react | 프론트 개발 서버·빌드 | MIT |
| Pretendard (웹폰트, CDN) | 글꼴 | SIL Open Font License 1.1 |

## 외부 API · 데이터
| 이름 | 용도 | 이용 조건 |
|---|---|---|
| 카카오 로컬 API | 주소·좌표·주변 기관 검색 | Kakao Developers 이용약관 |
| (개발 진행하며 추가) | | |

## 신규개발분 (날짜별)
| 날짜 | 내용 | 커밋 |
|---|---|---|
| 2026-09-29 | 문제정의·Workflow 설계서, 대회 규정 정리, 저장소 초기화 | 64b4211 |
| 2026-10-01 | Agent 골격: 입력 안전 점검(개인정보 가림·긴급상황·지시 주입 감지), 문제 분석, 처리 계획(보정 포함), 정보 판단·추가 질문 루프, LLM 실패 시 규칙 엔진 대체, 스트리밍 API, 테스트 11건 | 3a58ddf |
| 2026-10-01 | 최소 화면: 대화창 + Agent 작업 기록(단계별 판단·근거·판단 엔진 표시), 개인정보 가림·긴급상황 안내 표시 | |
