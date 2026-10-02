# AI민원길잡이

생활불편을 평소 말투로 입력하면 AI Agent가 문제를 분석하고, 처리 계획을 세우고, 부족한 정보를 되묻고, 담당 기관과 민원 초안을 준비해 주는 서비스입니다.
제4회 경남 AI·SW 경진대회 (대학부 · 사회문제 해결형 AI Agent) 출품작 · 설계: [docs/design.md](docs/design.md)

## Agent Workflow

```
입력 → [안전 점검] 개인정보 가림·긴급상황·지시 주입 감지
     → [문제 분석] 유형·긴급도
     → [처리 계획] 단계·사용할 Tool 결정 (누락 시 자동 보정)
     → [정보 판단] ⇄ [추가 질문] (최대 2회, 대화 상태 저장)
     → [Tool 실행] 위치 확인(카카오) → 관할 기관 검색(경찰서·행정복지센터) → 담당 부서·절차 조회
     → [담당 기관 판단] 주 담당 기관·제출 창구·할 일
     → [민원 초안 작성] ⇄ [초안 검증] 연락처·개인정보·위치·분량 + AI 검토 (문제 시 다시 작성, 최대 2회)
     → 민원 패키지 → (사용자 수정 요청 → 다시 작성)
```

- 판단 엔진: Claude. 이 PC에 설치·로그인된 **Claude Code(`claude -p`)를 단계마다 실행**해 판단하므로 LLM API 키가 필요 없습니다. Claude Code가 없거나 호출이 실패하면 **규칙 엔진으로 자동 대체**하고 작업 기록에 표시합니다.
- 화면 오른쪽 **Agent 작업 기록**에 단계별 판단·근거·Tool 호출·검증 결과가 실시간으로 남습니다.
- 최종 민원은 사용자가 확인·수정한 뒤 **직접 제출**합니다 (자동 제출하지 않음).

## 실행 방법 (Windows PowerShell)

필요: Python 3.11+, Node.js 20+, (AI 판단을 쓸 때) Claude Code 설치·로그인

**1. 백엔드** (터미널 1)

```bash
cd backend
```
```bash
python -m venv .venv
```
```bash
.venv\Scripts\pip install -r requirements.txt
```
```bash
copy .env.example .env
```
```bash
.venv\Scripts\uvicorn minwon.api:app --app-dir . --reload --port 8000
```

`.env`의 `LLM_PROVIDER=rule`이면 규칙 엔진으로 동작합니다. Claude로 판단하려면 `LLM_PROVIDER=claude_code`로 바꾸세요. 터미널에서 `claude auth status`가 `"loggedIn": true`이면 준비된 것입니다 (모델은 `CLAUDE_MODEL`, 기본 `sonnet`). 민원 1건에 Claude를 6~8번 부르고, 단계마다 5~35초 걸립니다. 사용량은 로그인한 Claude 요금제 한도에서 차감됩니다.
위치·기관 검색에는 `KAKAO_REST_API_KEY`(카카오 디벨로퍼스 REST API 키, 카카오맵 사용 설정 ON)가 필요하며, 없으면 문장에서 지역명을 추출해 일반 안내로 대체합니다.

**2. 프론트엔드** (터미널 2)

```bash
cd frontend
```
```bash
npm install
```
```bash
npm run dev
```

브라우저에서 http://localhost:5173 접속.

**테스트**

```bash
cd backend
```
```bash
.venv\Scripts\python -m pytest -q
```

## 새 PC·팀원 개발환경 맞추기

**1. 설치할 것:** Git, Python 3.11 이상, Node.js 20 이상, Claude Code (AI 판단 엔진 겸 코딩 도구. 설치 후 터미널에서 `claude`를 한 번 실행해 로그인)

**2. 코드 받기**

```bash
git clone https://github.com/JiHwan-2/minwon-agent.git
```

받은 뒤 위 "실행 방법"의 1·2번을 그대로 따라 합니다. 패키지 버전은 `requirements.txt`와 `package-lock.json`에 고정되어 있어 어느 PC에서나 같은 버전이 설치됩니다.

**3. 키·로그인 (`backend\.env`)** — 저장소에 없으니 PC마다 직접 넣습니다. 채팅·메일로 키를 주고받지 않습니다.

| 구분 | 받는 방법 | 비고 |
|---|---|---|
| 카카오 REST API 키 | 팀장이 카카오 디벨로퍼스 앱의 **멤버** 메뉴에서 팀원을 초대 → 팀원이 자기 계정으로 콘솔의 **앱 → 플랫폼 키**에서 확인 | 같은 앱의 키라 결과가 같음 |
| Claude (판단 엔진) | 키 없음. 각자 PC에서 Claude Code에 **자기 계정으로 로그인** | `LLM_PROVIDER=claude_code`. 계정을 나눠 쓰지 않음 |
| 키가 없을 때 | `LLM_PROVIDER=rule`, `KAKAO_REST_API_KEY` 비워 두기 | 규칙 엔진·문장 기반 지역 추출로 동작 |

**4. 확인:** `pytest`가 모두 통과하고 화면에서 예시 문장이 끝까지 진행되면 준비 완료입니다.

**5. Claude Code를 쓴다면:** 저장소의 `CLAUDE.md`(작업 지침)와 `.claude/skills/gn-contest`(대회 규정)를 자동으로 읽어 같은 규칙으로 작업합니다.

## 협업 규칙

| 구분 | 규칙 |
|---|---|
| 역할 | 김지환: `backend/` (AI·Agent) · 서준호: `frontend/` (화면). 상대 폴더를 크게 고칠 땐 먼저 상의 |
| 시작 전 | `git pull`로 최신 코드 받기 |
| 작업 | 기능마다 브랜치 만들기: `git switch -c feat/기능이름` |
| 커밋 | 테스트 통과 후 한국어 메시지로 커밋, 바로 `git push` |
| 합치기 | GitHub에서 Pull Request → 상대가 확인 → `main`에 병합 |
| 기록 | 기능을 마치면 `docs/sources.md` 신규개발분 표에 한 줄 추가 |
| 금지 | API 키 커밋, 다른 프로젝트 코드 복사, 상의 없는 강제 푸시 |

## 구조

```
backend/minwon/
  api.py              세션 생성·메시지 처리(단계별 스트리밍)·상태 조회 API
  safety.py           개인정보 가림, 긴급상황·지시 주입 감지
  settings.py         .env 설정
  knowledge/          생활불편 유형·필수 정보, 담당 부서·창구·절차·증빙 지식베이스
  tools/              카카오 로컬 API, 위치 확인·주변 기관 검색, 지식베이스 조회
  agent/
    graph.py          LangGraph 워크플로
    nodes.py          guard · understand · plan · check · ask · act · decide · draft · review
    brain.py          Claude Code(claude -p) 판단 엔진 + 실패 시 규칙 엔진 대체
    rules.py          규칙 기반 판단 엔진
    schemas.py        단계별 출력 구조
    prompts.py        단계별 지시문
frontend/src/
  App.jsx             상태 관리·이벤트 처리
  components/         Chat(대화) · AgentLog(작업 기록) · PackageCard(민원 패키지)
docs/
  design.md           문제정의·Workflow·Tool·예상 오류·일정
  sources.md          출처·AI 활용·신규개발분 기록
```
