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

- 판단 엔진: Claude(기본) 또는 GPT. 키가 없거나 호출이 실패하면 **규칙 엔진으로 자동 대체**하고 작업 기록에 표시합니다.
- 화면 오른쪽 **Agent 작업 기록**에 단계별 판단·근거·Tool 호출·검증 결과가 실시간으로 남습니다.
- 최종 민원은 사용자가 확인·수정한 뒤 **직접 제출**합니다 (자동 제출하지 않음).

## 실행 방법 (Windows PowerShell)

필요: Python 3.11+, Node.js 20+

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

`.env`의 `LLM_PROVIDER=rule`이면 API 키 없이 동작합니다. Claude를 쓰려면 `LLM_PROVIDER=anthropic`과 `ANTHROPIC_API_KEY`를 입력하세요.
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
    brain.py          Claude/GPT 판단 엔진 + 실패 시 규칙 엔진 대체
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
