# AI민원길잡이 — 작업 지침

제4회 경남 AI·SW 경진대회(대학부 · 01 사회문제 해결형 AI Agent) 출품작.
대회 규정·심사기준·제출물·일정은 **`.claude/skills/gn-contest/SKILL.md`를 먼저 읽고** 판단한다.
설계는 `docs/design.md`, 출처·신규개발분 기록은 `docs/sources.md`.

## 팀과 역할
| 구분 | 담당 | 주 작업 폴더 |
|---|---|---|
| 김지환 (팀장) | AI·Agent 개발, Workflow 설계 | `backend/` |
| 서준호 | Frontend 개발, 서비스 구현 | `frontend/` |

다른 사람 담당 폴더를 크게 고칠 때는 먼저 상의한다 (충돌 방지).

## 반드시 지킬 원칙
- 모든 코드는 이 저장소에서 대회 개발기간(2026-09-29 ~ 10-06) 중 작성한다. 다른 프로젝트·폴더의 코드를 복사해 오지 않는다.
- **제출 마감 2026-10-06 낮 12:00.** 마감 후 핵심기능·소스 변경 금지.
- API 키는 `backend/.env`에만 둔다. 커밋하거나 채팅·문서에 붙여 넣지 않는다.
- 기능을 마치면 `docs/sources.md`의 신규개발분 표에 날짜·내용·커밋을 추가한다. 새 오픈소스·API·데이터를 쓰면 같은 파일에 출처·라이선스를 적는다.
- 시민에게 주는 안내는 정확해야 한다. 공식 근거가 없는 것을 '필수'라고 하지 않는다 (증빙 level 규칙). 부서명은 "교통행정과 등"처럼 일반 표현을 쓰고 "지자체마다 다를 수 있음"을 유지한다.
- 민원은 자동 제출하지 않는다. 사용자가 확인 후 직접 제출한다.

## 실행 명령 (Windows PowerShell 기준 — `&&` 를 쓰지 말고 한 줄씩)
```
cd backend
.venv\Scripts\uvicorn minwon.api:app --app-dir . --reload --port 8000
.venv\Scripts\python -m pytest -q
.venv\Scripts\python scripts\run_testcases.py --only TC1   (실제 서버로 대표 테스트케이스 실행, 결과는 docs/testcases.md)
.venv\Scripts\python scripts\run_eval.py   (정확도 평가 세트 eval/dataset.json, --parts e2e는 서버 필요. 결과는 docs/eval/)
cd frontend
npm run dev
```
- 판단 엔진: `backend/.env`의 `LLM_PROVIDER=claude_code`면 로그인된 Claude Code(`claude -p`)로, `rule`이면 규칙 엔진으로 동작한다. LLM API 키는 쓰지 않는다.
- 자동 테스트는 항상 규칙 엔진과 가짜 응답(`tests/fake_kakao.py`, `tests/test_claude_code_brain.py`의 FakeClaude, `tests/test_cases_tool.py`의 FakeApi)을 써서 실제 Claude·카카오·공공데이터를 부르지 않는다.
- 첫 설치 방법은 README의 "새 PC·팀원 개발환경 맞추기".

## 구조 한눈에
```
backend/minwon/
  api.py        세션·메시지(NDJSON 스트리밍) API
  safety.py     개인정보 가림, 긴급상황·지시 주입 감지
  agent/        LangGraph 워크플로 (graph.py), 단계(nodes.py), 판단 엔진(brain.py: Claude Code `claude -p` → 실패 시 rules.py)
  tools/        카카오 로컬 API, 위치 확인·후보, 주변 기관, 지식베이스 조회, 비슷한 민원 사례(공공데이터), 민원 패키지 PDF
  knowledge/    생활불편 유형·필수 정보(categories.json), 담당 부서·창구·절차·증빙(agencies.json)
frontend/src/
  App.jsx       스트리밍 이벤트 → 화면 상태
  components/   Chat(대화) · AgentLog(작업 기록) · PackageCard(민원 패키지)
```
Workflow: guard → understand → plan → check ⇄ ask → locate ⇄ confirm_location → act → decide → draft ⇄ review → deliver (완성 후 수정 요청 → draft)
understand에서 Claude가 입력 확인: 민원 아님·불분명·다른 창구(소비자 피해·임금체불·사기·개인 간 분쟁 → agencies.json의 referrals)면 안내만 하고 끝. 위기 표현은 safety.py가 AI보다 먼저 109 안내
대화 도중 말은 agent/topic.py가 판단: 다른 종류의 민원이면 새 thread로 처음부터, 관계없는 말이면 진행하지 않고 안내. 중단 버튼은 agent/cancel.py(claude 프로세스 종료) → 그 턴 직전 체크포인트로 되돌림

## 작업 흐름
1. 시작 전 `git pull`
2. 각자 기능 브랜치에서 작업: `git switch -c feat/기능이름`
3. 변경 → `pytest` 통과 → 화면 변경이면 브라우저에서 직접 확인. 지시문(prompts.py)·지식베이스를 고쳤으면 `run_eval.py`로 정확도가 떨어지지 않았는지 확인
4. 커밋 메시지: 한국어. 첫 줄은 무엇을 했는지, 본문은 왜 했는지
5. 커밋하면 바로 push (`git push -u origin 브랜치` 처음 한 번, 이후 `git push`)
6. GitHub에서 Pull Request → 상대가 확인 → `main`에 병합
7. 강제 푸시(force push)·기록 재작성은 팀원과 상의 후에만

## 설명·문서 스타일
- 사용자에게 설명할 때 분류가 있으면 "구분 | 내용 | 예" 표 형식을 쓴다.
- 명령어는 PowerShell 기준으로 한 줄씩 안내한다.
- 화면 문구·민원 문장은 쉬운 한국어, 존댓말.
