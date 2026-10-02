"""정확도 평가 세트(eval/dataset.json)를 실제 Claude로 돌려 정답과 얼마나 맞는지 숫자로 남긴다.

- understand: 입력 확인(민원/다른 창구/불분명/민원 아님), 생활불편 유형, 다른 창구 코드, 안전 감지(개인정보·긴급·위기·지시 주입)
- turn: 대화 도중 말 판단(이어지는 말/다른 민원/관계없는 말). 짧은 답은 실제 서비스처럼 판단 없이 '이어지는 말'로 처리
- e2e: 실행 중인 서버로 처음부터 끝까지 → 담당 기관·부서·위치 (질문에는 '모름', 위치 후보는 1번으로 자동 답변)

자동 테스트(pytest)와 달리 실제 Claude·카카오·공공데이터를 부른다.
사용 (backend 폴더에서):
  .venv\\Scripts\\python scripts\\run_eval.py                         (understand·turn, 서버 불필요, 약 2~3분)
  .venv\\Scripts\\python scripts\\run_eval.py --parts e2e              (서버 필요, 약 5~10분)
  .venv\\Scripts\\python scripts\\run_eval.py --parts understand --only U01,R01 --note "지시문 수정 후"
결과: docs/eval/날짜-시각.md(요약·틀린 것) + 같은 이름 .json(전체 기록)
"""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minwon import safety  # noqa: E402
from minwon.agent import topic  # noqa: E402
from minwon.agent.brain import get_brain  # noqa: E402
from minwon.settings import settings  # noqa: E402

DATASET = ROOT / "eval" / "dataset.json"
OUT_DIR = ROOT.parent / "docs" / "eval"
FILTERED = {"unclear", "not_complaint"}  # 민원 흐름을 시작하지 않는 판단


def accepts(expected, value) -> bool:
    return value in (expected if isinstance(expected, list) else [expected])


def show(expected) -> str:
    return " 또는 ".join(expected) if isinstance(expected, list) else str(expected)


def pct(ok: int, total: int) -> str:
    return f"{ok}/{total} ({ok / total * 100:.1f}%)" if total else "-"


# ---- 입력 확인 ----

def run_understand(case: dict) -> dict:
    masked = safety.mask_pii(case["text"])  # 서비스와 같이 개인정보를 가린 뒤 판단
    started = time.perf_counter()
    out = get_brain().call("understand", masked.text)
    seconds = round(time.perf_counter() - started, 1)
    u = out.value
    got = {"intent": u.intent, "category": u.category, "referral": u.referral, "title": u.title, "reply": u.reply}
    checks = {}
    if "intent" in case:
        checks["intent"] = accepts(case["intent"], u.intent)
    if "category" in case:
        checks["category"] = u.intent == "complaint" and accepts(case["category"], u.category)
    if "referral" in case:
        checks["referral"] = u.intent == "referral" and u.referral == case["referral"]
    detected = {
        "pii": sorted(f["kind"] for f in masked.findings),
        "emergency": safety.is_emergency(masked.text),
        "crisis": safety.is_crisis(masked.text),
        "injection": safety.looks_like_injection(masked.text),
    }
    for key, want in case.get("safety", {}).items():
        checks[f"safety.{key}"] = detected[key] == (sorted(want) if key == "pii" else want)
    return {**case, "got": got, "detected": detected, "checks": checks, "ok": all(checks.values()),
            "source": out.source, "error": out.error, "seconds": seconds}


def summarize_understand(rows: list[dict]) -> dict:
    def expected(r):
        return r.get("intent")

    intent_rows = [r for r in rows if "intent" in r["checks"]]
    complaints = [r for r in rows if expected(r) == "complaint"]
    to_filter = [r for r in rows if expected(r) and all(i in FILTERED for i in (expected(r) if isinstance(expected(r), list) else [expected(r)]))]
    referrals = [r for r in rows if "referral" in r["checks"]]
    categories = [r for r in rows if "category" in r["checks"]]
    safety_rows = [r for r in rows if any(k.startswith("safety.") for k in r["checks"])]
    groups: dict[str, list[int]] = {}
    for r in rows:
        g = groups.setdefault(r["group"], [0, 0])
        g[0] += r["ok"]
        g[1] += 1
    llm = [r["seconds"] for r in rows if r["source"] == "llm"]
    return {
        "cases": len(rows),
        "all_ok": sum(r["ok"] for r in rows),
        "intent": [sum(r["checks"]["intent"] for r in intent_rows), len(intent_rows)],
        "blocked_complaints": [sum(r["got"]["intent"] != "complaint" for r in complaints), len(complaints)],
        "filtered": [sum(r["got"]["intent"] in FILTERED for r in to_filter), len(to_filter)],
        "referral": [sum(r["checks"]["referral"] for r in referrals), len(referrals)],
        "category": [sum(r["checks"]["category"] for r in categories), len(categories)],
        "safety": [sum(all(v for k, v in r["checks"].items() if k.startswith("safety.")) for r in safety_rows), len(safety_rows)],
        "groups": groups,
        "fallback": sum(r["source"] != "llm" for r in rows),
        "seconds_avg": round(statistics.mean(llm), 1) if llm else None,
        "seconds_max": max(llm) if llm else None,
    }


# ---- 대화 도중 ----

def run_turn(case: dict, default: dict) -> dict:
    current, questions = case.get("current", default["current"]), case.get("questions", default["questions"])
    text = safety.mask_pii(case["text"]).text
    started = time.perf_counter()
    if not topic.worth_checking(text, case["stage"]):  # 서비스와 같이 짧은 답은 판단 없이 답변으로
        kind, reason, source, error = "continue", "짧은 답이라 판단 없이 답변으로 받음", "skip", ""
    else:
        ctx = {"current": current, "stage": case["stage"],
               "pending_questions": questions if case["stage"] == "asking" else [], "message": text}
        out = get_brain().call("switch", ctx)
        kind, reason, source, error = out.value.kind, out.value.reason, out.source, out.error
    seconds = round(time.perf_counter() - started, 1)
    ok = kind == case["kind"]
    return {**case, "got": {"kind": kind, "reason": reason}, "checks": {"kind": ok}, "ok": ok,
            "source": source, "error": error, "seconds": seconds}


def summarize_turn(rows: list[dict]) -> dict:
    def by(kind):
        return [r for r in rows if r["kind"] == kind]

    llm = [r["seconds"] for r in rows if r["source"] == "llm"]
    return {
        "cases": len(rows),
        "all_ok": sum(r["ok"] for r in rows),
        "missed_answers": [sum(r["got"]["kind"] == "off_topic" for r in by("continue")), len(by("continue"))],
        "off_topic": [sum(r["ok"] for r in by("off_topic")), len(by("off_topic"))],
        "new_complaint": [sum(r["ok"] for r in by("new_complaint")), len(by("new_complaint"))],
        "skipped": sum(r["source"] == "skip" for r in rows),
        "fallback": sum(r["source"] not in ("llm", "skip") for r in rows),
        "seconds_avg": round(statistics.mean(llm), 1) if llm else None,
    }


# ---- 처음부터 끝까지 ----

def send(client: httpx.Client, base: str, sid: str, text: str) -> list[dict]:
    with client.stream("POST", f"{base}/api/sessions/{sid}/messages", json={"text": text}, timeout=900) as resp:
        resp.raise_for_status()
        return [json.loads(line) for line in resp.iter_lines() if line.strip()]


def run_e2e(case: dict, base: str) -> dict:
    answers = []
    started = time.perf_counter()
    with httpx.Client() as client:
        sid = client.post(f"{base}/api/sessions", timeout=10).json()["session_id"]
        events = send(client, base, sid, case["text"])
        while events and events[-1]["type"] == "ask" and len(answers) < 4:
            answer = "1" if events[-1]["options"] else "모름"
            answers.append(answer)
            events = send(client, base, sid, answer)
        state = client.get(f"{base}/api/sessions/{sid}", timeout=30).json()
    seconds = round(time.perf_counter() - started, 1)

    agency = (state.get("decision") or {}).get("agency") or {}
    location = state.get("location") or {}
    got = {
        "end": events[-1]["type"] if events else "",
        "category": (state.get("understanding") or {}).get("category", ""),
        "agency": agency.get("agency", ""),
        "unit": agency.get("unit", ""),
        "sigungu": location.get("sigungu", ""),
        "address": location.get("address", ""),
        "review_passed": (state.get("review") or {}).get("passed"),
        "review_issues": (state.get("review") or {}).get("issues", []),
        "fallback_steps": [x["node"] for x in state.get("log") or [] if x.get("source") == "rule_fallback"],
        "fallback_errors": sorted({x.get("error", "")[:120] for x in state.get("log") or [] if x.get("source") == "rule_fallback"}),
        "answers": answers,
    }
    checks = {
        "finished": got["end"] == "ready",
        "category": got["category"] == case["category"],
        "sigungu": case["sigungu"] in got["sigungu"],
        "agency": any(k in got["agency"] for k in case["agency"]),
        "unit": any(k in got["unit"] for k in case["unit"]),
    }
    return {**case, "got": got, "checks": checks, "ok": all(checks.values()), "seconds": seconds}


def summarize_e2e(rows: list[dict]) -> dict:
    def count(key):
        return [sum(r["checks"][key] for r in rows), len(rows)]

    return {
        "cases": len(rows),
        "all_ok": sum(r["ok"] for r in rows),
        "agency_and_unit": [sum(r["checks"]["agency"] and r["checks"]["unit"] for r in rows), len(rows)],
        **{k: count(k) for k in ("finished", "category", "sigungu", "agency", "unit")},
        "review_passed": [sum(bool(r["got"]["review_passed"]) for r in rows), len(rows)],
        "fallback_cases": sum(bool(r["got"]["fallback_steps"]) for r in rows),
        "seconds_avg": round(statistics.mean(r["seconds"] for r in rows), 1) if rows else None,
    }


# ---- 보고서 ----

def report(result: dict) -> str:
    lines = [f"# 정확도 평가 결과 ({result['run_at']})", "",
             f"- 판단 엔진: {result['model']} · 평가 세트: `backend/eval/dataset.json`"]
    if result["note"]:
        lines.append(f"- 메모: {result['note']}")
    lines += ["", "## 요약", "", "| 항목 | 결과 | 설명 |", "|---|---|---|"]
    parts = result["parts"]
    if "understand" in parts:
        s = parts["understand"]["summary"]
        lines += [
            f"| 입력 확인 정확도 | {pct(*s['intent'])} | 민원·다른 창구·불분명·민원 아님 판단 |",
            f"| 진짜 민원을 막은 비율 | {pct(*s['blocked_complaints'])} | 낮을수록 좋음. 민원인데 흐름을 시작하지 않은 경우 |",
            f"| 걸러야 할 입력을 거른 비율 | {pct(*s['filtered'])} | 잡담·의미 없는 말·불분명한 말을 민원 흐름에 넣지 않음 |",
            f"| 다른 창구 정확도 | {pct(*s['referral'])} | 소비자 피해·임금체불·사기·개인 간 분쟁 → 맞는 창구 |",
            f"| 생활불편 유형 정확도 | {pct(*s['category'])} | 유형이 맞아야 담당 부서가 맞음 |",
            f"| 안전 감지 | {pct(*s['safety'])} | 개인정보·긴급상황·위기 표현·지시 주입 (규칙, AI 판단과 무관) |",
            f"| 문제 분석 판단 시간 | 평균 {s['seconds_avg']}초 · 최대 {s['seconds_max']}초 | Claude 호출 1회 |",
        ]
    if "turn" in parts:
        s = parts["turn"]["summary"]
        lines += [
            f"| 대화 도중 판단 정확도 | {pct(s['all_ok'], s['cases'])} | 이어지는 말·다른 민원·관계없는 말 |",
            f"| 답·수정 요청을 관계없는 말로 오해 | {pct(*s['missed_answers'])} | 낮을수록 좋음 |",
            f"| 관계없는 말을 거른 비율 | {pct(*s['off_topic'])} | |",
            f"| 대화 도중 판단 시간 | 평균 {s['seconds_avg']}초 | 짧은 답 {s['skipped']}건은 판단 없이 바로 처리 |",
        ]
    if "e2e" in parts:
        s = parts["e2e"]["summary"]
        lines += [
            f"| 담당 기관 정확도 (처음부터 끝까지) | {pct(*s['agency_and_unit'])} | 기관 이름과 담당 부서가 모두 맞음 |",
            f"| 위치(시·군·구) 확인 | {pct(*s['sigungu'])} | 카카오 지도 기준 |",
            f"| 초안 검증 통과 | {pct(*s['review_passed'])} | |",
            f"| 전체 흐름 시간 | 평균 {s['seconds_avg']}초 | 질문 답변 포함 |",
        ]
    fallback = sum(parts[p]["summary"].get("fallback", 0) for p in ("understand", "turn") if p in parts)
    if "e2e" in parts:
        fallback += parts["e2e"]["summary"]["fallback_cases"]
    lines += ["", f"규칙 엔진으로 대체된 판단: {fallback}건 (0이면 모든 판단을 Claude가 함)"]
    if fallback:
        errors = {r["error"][:120] for p in ("understand", "turn") for r in parts.get(p, {}).get("rows", []) if r.get("error")}
        errors |= {e for r in parts.get("e2e", {}).get("rows", []) for e in r["got"]["fallback_errors"] if e}
        lines += ["", "> 주의: Claude 호출이 실패해 규칙 엔진이 대신한 판단이 있어 Claude 정확도로 볼 수 없습니다. 원인을 고친 뒤 다시 실행하세요.", ""]
        lines += [f"- {e}" for e in sorted(errors)] or ["- (오류 내용 없음)"]

    if "understand" in parts:
        lines += ["", "## 입력 확인 그룹별", "", "| 그룹 | 맞음 |", "|---|---|"]
        lines += [f"| {g} | {pct(ok, n)} |" for g, (ok, n) in parts["understand"]["summary"]["groups"].items()]

    wrong = []
    for name in ("understand", "turn", "e2e"):
        for r in parts.get(name, {}).get("rows", []):
            if r["ok"]:
                continue
            failed = ", ".join(k for k, v in r["checks"].items() if not v)
            if name == "understand":
                want = " · ".join(x for x in (show(r.get("intent", "")), show(r.get("category", "")), r.get("referral", "")) if x)
                got = f"{r['got']['intent']} · {r['got']['category']}" + (f" · {r['got']['referral']}" if r["got"]["intent"] == "referral" else "")
            elif name == "turn":
                want, got = f"{r['stage']} · {r['kind']}", f"{r['got']['kind']} ({r['got']['reason']})"
            else:
                want = f"{r['category']} · {'/'.join(r['agency'])} {'/'.join(r['unit'])} · {r['sigungu']}"
                got = f"{r['got']['category']} · {r['got']['agency']} {r['got']['unit']} · {r['got']['sigungu']}"
            wrong.append(f"| {r['id']} | {r['text']} | {want} | {got} | {failed} |")
    lines += ["", "## 틀린 것", ""]
    lines += (["| ID | 입력 | 정답 | 결과 | 틀린 항목 |", "|---|---|---|---|---|", *wrong] if wrong else ["없음"])
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="정확도 평가 세트 실행")
    ap.add_argument("--parts", default="understand,turn", help="understand,turn,e2e 중 쉼표로")
    ap.add_argument("--only", default="", help="실행할 ID (예: U01,T05,A03)")
    ap.add_argument("--base", default="http://localhost:8000", help="e2e에 쓸 서버 주소")
    ap.add_argument("--workers", type=int, default=6, help="동시에 돌릴 Claude 판단 수")
    ap.add_argument("--e2e-workers", type=int, default=3, help="동시에 돌릴 전체 흐름 수")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    if ({"understand", "turn"} & set(parts)) and get_brain().mode != "llm":
        print("판단 엔진이 Claude가 아닙니다 (backend/.env의 LLM_PROVIDER=claude_code 확인). 규칙 엔진은 평가하지 않습니다.")
        return 2

    data = json.loads(DATASET.read_text(encoding="utf-8"))
    result = {"run_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": settings.model_label, "note": args.note, "parts": {}}

    jobs = {
        "understand": (lambda c: run_understand(c), summarize_understand, args.workers),
        "turn": (lambda c: run_turn(c, data["turn_default"]), summarize_turn, args.workers),
        "e2e": (lambda c: run_e2e(c, args.base), summarize_e2e, args.e2e_workers),
    }
    for name in parts:
        run, summarize, workers = jobs[name]
        cases = [c for c in data[name] if not only or c["id"] in only]
        if not cases:
            continue
        print(f"\n[{name}] {len(cases)}건 실행")
        rows = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run, c): c for c in cases}
            for f in as_completed(futures):
                r = f.result()
                rows.append(r)
                print(f"  {'OK' if r['ok'] else 'XX'} {r['id']} {r['text'][:30]} ({r['seconds']}초)")
        rows.sort(key=lambda r: r["id"])
        result["parts"][name] = {"summary": summarize(rows), "rows": rows}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d-%H%M")
    (out / f"{stem}.json").write_bytes(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    text = report(result)
    (out / f"{stem}.md").write_bytes(text.encode("utf-8"))
    print("\n" + text)
    print(f"저장: {out / stem}.md / .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
