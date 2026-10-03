"""정확도 평가 세트(eval/dataset.json)를 실제 Claude로 돌려 정답과 얼마나 맞는지 숫자로 남긴다.

- understand: 입력 확인(민원/다른 창구/불분명/민원 아님), 생활불편 유형, 다른 창구 코드, 안전 감지(개인정보·긴급·위기·지시 주입)
- turn: 대화 도중 말 판단(이어지는 말/다른 민원/관계없는 말). 짧은 답은 실제 서비스처럼 판단 없이 '이어지는 말'로 처리
- e2e: 실행 중인 서버로 처음부터 끝까지 → 담당 기관·부서·위치 (질문에는 '모름', 위치 후보는 1번으로 자동 답변)
- revision: 서버로 민원을 완성한 뒤 시민이 수정을 요청 → 요청대로 다시 썼는지(넣기·빼기·고치기·줄이기·제목·규칙 지키기·번역),
  따르면 안 되는 요청은 반영하지 않고 이유를 알렸는지

자동 테스트(pytest)와 달리 실제 Claude·카카오·공공데이터를 부른다.
사용 (backend 폴더에서):
  .venv\\Scripts\\python scripts\\run_eval.py                         (understand·turn, 서버 불필요, 약 2~3분)
  .venv\\Scripts\\python scripts\\run_eval.py --parts e2e              (서버 필요, 약 5~10분)
  .venv\\Scripts\\python scripts\\run_eval.py --parts revision         (서버 필요, 약 15~20분)
  .venv\\Scripts\\python scripts\\run_eval.py --parts understand --only U01,R01 --note "지시문 수정 후"
  .venv\\Scripts\\python scripts\\run_eval.py --compare                (실행 없이 저장된 결과들을 비교해 회차마다 달라진 문항 찾기)
결과: docs/eval/날짜-시각.md(요약·틀린 것) + 같은 이름 .json(전체 기록), 비교는 docs/eval/stability-날짜-시각.md
"""

import argparse
import glob
import json
import re
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
    got = {"intent": u.intent, "category": u.category, "service": u.service, "referral": u.referral, "language": u.language,
           "title": u.title, "reply": u.reply}
    detected = {
        "pii": sorted(f["kind"] for f in masked.findings),
        "emergency": safety.is_emergency(masked.text),
        "crisis": safety.is_crisis(masked.text),
        "injection": safety.looks_like_injection(masked.text),
    }
    checks = score_understand(case, got, detected)
    return {**case, "got": got, "detected": detected, "checks": checks, "ok": all(checks.values()),
            "source": out.source, "error": out.error, "seconds": seconds}


def score_understand(case: dict, got: dict, detected: dict) -> dict:
    checks = {}
    if "intent" in case:
        checks["intent"] = accepts(case["intent"], got["intent"])
    if "category" in case:
        checks["category"] = got["intent"] == "complaint" and accepts(case["category"], got["category"])
    if "referral" in case:
        checks["referral"] = got["intent"] == "referral" and got["referral"] == case["referral"]
    if "service" in case:
        checks["service"] = got["intent"] == "service" and got.get("service") == case["service"]
    for key, want in case.get("safety", {}).items():
        checks[f"safety.{key}"] = detected[key] == (sorted(want) if key == "pii" else want)
    if "language" in case:
        checks["language"] = got.get("language") == case["language"]
        if got["intent"] in FILTERED:  # 민원이 아니라고 안내했으면 그 안내도 시민의 언어여야 한다
            checks["reply_lang"] = written_in(got["reply"], case["language"])
    if case.get("no_contact"):  # 연락처를 물어도 지어내지 않아야 한다 (정해진 안내문은 서버가 따로 붙임)
        checks["no_contact"] = not CONTACT.search(got["reply"])
    return checks


CONTACT = re.compile(r"\d{2,4}-\d{3,4}-\d{4}|\b\d{3,4}-\d{4}\b|https?://|www\.")
_SCRIPTS = {
    "ko": re.compile(r"[가-힣]"),
    "zh": re.compile(r"[一-鿿]"),
    "vi": re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.IGNORECASE),
}


def written_in(text: str, lang: str) -> bool:
    """안내 문장이 그 언어로 쓰였는지 글자 모양으로 확인한다 (영어는 한글·한자가 없고 라틴 문자로)."""
    if not text.strip():
        return False
    if lang == "en":
        body = re.sub(r"'[^']*'|\"[^\"]*\"|“[^”]*”", "", text)  # 따옴표 안 예시(한국어 지명 등)는 빼고 본다
        return not _SCRIPTS["ko"].search(body) and not _SCRIPTS["zh"].search(body) and bool(re.search(r"[A-Za-z]{3,}", body))
    if lang == "zh":
        return bool(_SCRIPTS["zh"].search(text))
    return bool(_SCRIPTS[lang].search(text))


def summarize_understand(rows: list[dict]) -> dict:
    def expected(r):
        return r.get("intent")

    intent_rows = [r for r in rows if "intent" in r["checks"]]
    complaints = [r for r in rows if expected(r) == "complaint"]
    to_filter = [r for r in rows if expected(r) and all(i in FILTERED for i in (expected(r) if isinstance(expected(r), list) else [expected(r)]))]
    referrals = [r for r in rows if "referral" in r["checks"]]
    services = [r for r in rows if "service" in r["checks"]]
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
        "service": [sum(r["checks"]["service"] for r in services), len(services)],
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
    got = {"kind": kind, "reason": reason}
    checks = score_turn(case, got)
    return {**case, "got": got, "checks": checks, "ok": all(checks.values()),
            "source": source, "error": error, "seconds": seconds}


def score_turn(case: dict, got: dict) -> dict:
    return {"kind": got["kind"] == case["kind"]}


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
    checks = score_e2e(case, got)
    return {**case, "got": got, "checks": checks, "ok": all(checks.values()), "seconds": seconds}


def score_e2e(case: dict, got: dict) -> dict:
    return {
        "finished": got["end"] == "ready",
        "category": got["category"] == case["category"],
        "sigungu": case["sigungu"] in got["sigungu"],
        "agency": any(k in got["agency"] for k in case["agency"]),
        "unit": any(k in got["unit"] for k in case["unit"]),
    }


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


# ---- 완성 후 수정 요청 ----

DETOURS = {"off_topic", "answer", "topic_changed", "redirect", "crisis", "error", "ask", "cancelled"}  # 수정으로 이어지지 않은 응답


def _draft_of(state: dict) -> dict:
    pkg = state.get("package") or {}
    review = state.get("review") or {}
    tr = state.get("translation") or {}
    return {
        "title": pkg.get("title", ""), "body": pkg.get("body", ""), "version": pkg.get("version", 0), "reply": pkg.get("reply", ""),
        "evidence": [{"item": e["item"], "level": e["level"]} for e in pkg.get("evidence", [])],
        "review_passed": review.get("passed"), "review_issues": review.get("issues", []), "review_round": review.get("round"),
        "translation": {"version": tr.get("version"), "translated": tr.get("translated"), "body": tr.get("body", "")} if tr else None,
    }


def run_revision(case: dict, base: str, texts: dict) -> dict:
    """민원을 완성한 뒤 수정 요청을 보내고, 요청대로 다시 썼는지 본다 (완성까지의 질문에는 e2e처럼 자동 답변)."""
    started = time.perf_counter()
    steps = []
    with httpx.Client() as client:
        sid = client.post(f"{base}/api/sessions", timeout=10).json()["session_id"]
        events = send(client, base, sid, texts[case["base"]])
        answers = 0
        while events and events[-1]["type"] == "ask" and answers < 4:
            answers += 1
            events = send(client, base, sid, "1" if events[-1]["options"] else "모름")
        state = client.get(f"{base}/api/sessions/{sid}", timeout=30).json()
        before = _draft_of(state)
        drafts = [before]
        log_start = len(state.get("log") or [])
        for request in case["requests"]:
            t0 = time.perf_counter()
            events = send(client, base, sid, request)
            state = client.get(f"{base}/api/sessions/{sid}", timeout=30).json()
            types = [e["type"] for e in events]
            steps.append({"request": request, "end": types[-1] if types else "",
                          "detours": [e for e in types if e in DETOURS],
                          "seconds": round(time.perf_counter() - t0, 1),
                          "notes": [{k: e.get(k) for k in ("type", "message", "reason")} for e in events if e["type"] in DETOURS]})
            drafts.append(_draft_of(state))
    log = (state.get("log") or [])[log_start:]
    got = {
        "start_end": "ready" if before["version"] else "not_ready",
        "before": before, "after": drafts[-1], "previous": drafts[-2], "steps": steps,
        "agency": ((state.get("decision") or {}).get("agency") or {}).get("agency", ""),
        "revision_log": [f"{x['title']}: {x['detail']}" for x in log if x.get("node") in ("draft", "review", "translate")],
        "fallback_steps": [x["node"] for x in state.get("log") or [] if x.get("source") == "rule_fallback"],
        "fallback_errors": sorted({x.get("error", "")[:120] for x in state.get("log") or [] if x.get("source") == "rule_fallback"}),
    }
    checks = score_revision(case, got)
    return {**case, "text": " → ".join(case["requests"]), "got": got, "checks": checks, "ok": all(checks.values()),
            "seconds": round(time.perf_counter() - started, 1)}


def _plain(s: str) -> str:
    return re.sub(r"[\s'\"‘’“”「」]", "", s)


def score_revision(case: dict, got: dict) -> dict:
    """요청이 수정으로 이어졌는지(applied) + 문항별 기대(expect) + 다시 쓴 초안이 검증을 통과했는지."""
    before, after, previous = got["before"], got["after"], got["previous"]
    text = f"{after['title']}\n{after['body']}"
    expect = case["expect"]
    checks = {
        "applied": got["start_end"] == "ready" and all(s["end"] == "ready" and not s["detours"] for s in got["steps"])
                   and after["version"] >= before["version"] + len(case["requests"]),
        "review_passed": bool(after["review_passed"]),
    }
    if "contains" in expect:
        checks["contains"] = all(any(a in text for a in group) for group in expect["contains"])
    if "absent" in expect:
        checks["absent"] = not any(a in text for a in expect["absent"])
    if "shorter" in expect:
        checks["shorter"] = len(after["body"]) <= len(before["body"]) * expect["shorter"]
    if "shorter_than_previous" in expect:
        checks["shorter"] = len(after["body"]) <= len(previous["body"]) * expect["shorter_than_previous"]
    if "title" in expect:
        checks["title"] = _plain(after["title"]) == _plain(expect["title"])
    if "not_required" in expect:
        checks["not_required"] = not any(e["level"] == "required" and any(k in e["item"] for k in expect["not_required"])
                                         for e in after["evidence"])
    if expect.get("changed"):
        checks["changed"] = after["body"] != before["body"]
    if expect.get("explained"):
        checks["explained"] = bool(after.get("reply"))  # 반영하지 않은 요청이 있으면 시민에게 이유를 알렸는지
    if expect.get("translated"):
        tr = after["translation"] or {}
        checks["translated"] = bool(tr.get("translated")) and tr.get("version") == after["version"]
    return checks


def summarize_revision(rows: list[dict]) -> dict:
    def count(key):
        have = [r for r in rows if key in r["checks"]]
        return [sum(r["checks"][key] for r in have), len(have)]

    expected = [r for r in rows if set(r["checks"]) - {"applied", "review_passed"}]
    steps = [s for r in rows for s in r["got"]["steps"]]
    return {
        "cases": len(rows),
        "all_ok": sum(r["ok"] for r in rows),
        "applied": count("applied"),
        "expected": [sum(all(v for k, v in r["checks"].items() if k not in ("applied", "review_passed")) for r in expected), len(expected)],
        "review_passed": count("review_passed"),
        "fallback_cases": sum(bool(r["got"]["fallback_steps"]) for r in rows),
        "seconds_avg": round(statistics.mean(s["seconds"] for s in steps), 1) if steps else None,
    }


def revision_details(rows: list[dict]) -> list[str]:
    """요청 전후 초안을 나란히 보여 준다 (자동 채점이 못 보는 어조·자연스러움은 사람이 읽고 판단)."""
    lines = ["", "## 수정 요청 전후 초안", ""]
    for r in rows:
        g = r["got"]
        b, a = g["before"], g["after"]
        mark = "통과" if r["ok"] else "실패: " + ", ".join(k for k, v in r["checks"].items() if not v)
        lines += [f"### {r['id']} {r['kind']} — {mark}", ""]
        for s in g["steps"]:
            lines.append(f"- 요청: {s['request']} → {s['end']} ({s['seconds']}초)")
            lines += [f"  - {n['type']}: {n.get('message') or ''} {('(' + n['reason'] + ')') if n.get('reason') else ''}" for n in s["notes"]]
        lines += [f"- 기록: {x}" for x in g["revision_log"]]
        if a.get("reply"):
            lines.append(f"- 시민에게 한 답: {a['reply']}")
        lines += [f"- 담당 기관: {g['agency']} · 본문 {len(b['body'])}자 → {len(a['body'])}자 · 버전 {b['version']} → {a['version']}"]
        if a["review_issues"]:
            lines.append("- 남은 검증 의견: " + " / ".join(a["review_issues"]))
        changed = [f"{e['item']}({e['level']})" for e in a["evidence"]]
        lines += [f"- 증빙: {', '.join(changed)}", "", "<table><tr><th>요청 전</th><th>요청 후</th></tr><tr>",
                  f"<td valign=\"top\"><b>{b['title']}</b><br><br>{b['body'].replace(chr(10), '<br>')}</td>",
                  f"<td valign=\"top\"><b>{a['title']}</b><br><br>{a['body'].replace(chr(10), '<br>')}</td>", "</tr></table>", ""]
    return lines


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
            f"| 민원 서비스 분류 | {pct(*s.get('service', [0, 0]))} | 서류 발급·신고·신청 질문 → 맞는 민원 서비스 |",
            f"| 생활불편 유형 정확도 | {pct(*s['category'])} | 유형이 맞아야 담당 부서가 맞음 |",
            f"| 안전 감지 | {pct(*s['safety'])} | 개인정보·긴급상황·위기 표현·지시 주입 (규칙, AI 판단과 무관) |",
            f"| 문제 분석 판단 시간 | 평균 {s['seconds_avg']}초 · 최대 {s['seconds_max']}초 | Claude 호출 1회 |",
        ]
    if "turn" in parts:
        s = parts["turn"]["summary"]
        lines += [
            f"| 대화 도중 판단 정확도 | {pct(s['all_ok'], s['cases'])} | 이어지는 말·다른 민원·질문·관계없는 말 |",
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
    if "revision" in parts:
        s = parts["revision"]["summary"]
        lines += [
            f"| 수정 요청 반영 (문항 전체) | {pct(s['all_ok'], s['cases'])} | 요청대로 고침 + 다시 쓴 초안 검증 통과 |",
            f"| 수정 요청이 수정으로 이어짐 | {pct(*s['applied'])} | 관계없는 말·질문·새 민원으로 오해하지 않음 |",
            f"| 요청 내용대로 고침 | {pct(*s['expected'])} | 넣기·빼기·고치기·줄이기·제목·규칙 지키기 |",
            f"| 다시 쓴 초안 검증 통과 | {pct(*s['review_passed'])} | |",
            f"| 수정 요청 처리 시간 | 평균 {s['seconds_avg']}초 | 요청 1번당 |",
        ]
    fallback = sum(parts[p]["summary"].get("fallback", 0) for p in ("understand", "turn") if p in parts)
    for p in ("e2e", "revision"):
        if p in parts:
            fallback += parts[p]["summary"]["fallback_cases"]
    lines += ["", f"규칙 엔진으로 대체된 판단: {fallback}건 (0이면 모든 판단을 Claude가 함)"]
    if fallback:
        errors = {r["error"][:120] for p in ("understand", "turn") for r in parts.get(p, {}).get("rows", []) if r.get("error")}
        errors |= {e for p in ("e2e", "revision") for r in parts.get(p, {}).get("rows", []) for e in r["got"]["fallback_errors"] if e}
        lines += ["", "> 주의: Claude 호출이 실패해 규칙 엔진이 대신한 판단이 있어 Claude 정확도로 볼 수 없습니다. 원인을 고친 뒤 다시 실행하세요.", ""]
        lines += [f"- {e}" for e in sorted(errors)] or ["- (오류 내용 없음)"]

    if "understand" in parts:
        lines += ["", "## 입력 확인 그룹별", "", "| 그룹 | 맞음 |", "|---|---|"]
        lines += [f"| {g} | {pct(ok, n)} |" for g, (ok, n) in parts["understand"]["summary"]["groups"].items()]

    wrong = []
    for name in ("understand", "turn", "e2e", "revision"):
        for r in parts.get(name, {}).get("rows", []):
            if r["ok"]:
                continue
            failed = ", ".join(k for k, v in r["checks"].items() if not v)
            if name == "understand":
                want = " · ".join(x for x in (show(r.get("intent", "")), show(r.get("category", "")), r.get("referral", ""), r.get("service", "")) if x)
                got = f"{r['got']['intent']} · {r['got']['category']}" + (f" · {r['got']['referral']}" if r["got"]["intent"] == "referral" else "")                     + (f" · {r['got'].get('service')}" if r["got"]["intent"] == "service" else "")
            elif name == "turn":
                want, got = f"{r['stage']} · {r['kind']}", f"{r['got']['kind']} ({r['got']['reason']})"
            elif name == "revision":
                want, got = r["kind"], r["got"]["after"]["title"]
            else:
                want = f"{r['category']} · {'/'.join(r['agency'])} {'/'.join(r['unit'])} · {r['sigungu']}"
                got = f"{r['got']['category']} · {r['got']['agency']} {r['got']['unit']} · {r['got']['sigungu']}"
            wrong.append(f"| {r['id']} | {r['text']} | {want} | {got} | {failed} |")
    lines += ["", "## 틀린 것", ""]
    lines += (["| ID | 입력 | 정답 | 결과 | 틀린 항목 |", "|---|---|---|---|---|", *wrong] if wrong else ["없음"])
    if "revision" in parts:
        lines += revision_details(parts["revision"]["rows"])
    return "\n".join(lines) + "\n"


# ---- 여러 번 실행 비교 (흔들림) ----

PART_LABEL = {"understand": "입력 확인", "turn": "대화 도중", "e2e": "처음부터 끝까지", "revision": "수정 요청"}
SCORERS = {
    "understand": lambda case, row: score_understand(case, row["got"], row["detected"]),
    "turn": lambda case, row: score_turn(case, row["got"]),
    "e2e": lambda case, row: score_e2e(case, row["got"]),
    "revision": lambda case, row: score_revision(case, row["got"]),
}
SUMMARIZERS = {"understand": summarize_understand, "turn": summarize_turn, "e2e": summarize_e2e, "revision": summarize_revision}
METRICS = [
    ("understand", "입력 확인 문항 (모든 항목 정답)", lambda s: (s["all_ok"], s["cases"])),
    ("understand", "입력 확인 판단", lambda s: s["intent"]),
    ("understand", "진짜 민원을 막은 경우 (낮을수록 좋음)", lambda s: s["blocked_complaints"]),
    ("understand", "다른 창구", lambda s: s["referral"]),
    ("understand", "민원 서비스", lambda s: s.get("service", [0, 0])),
    ("understand", "생활불편 유형", lambda s: s["category"]),
    ("turn", "대화 도중 판단", lambda s: (s["all_ok"], s["cases"])),
    ("turn", "답·수정 요청을 관계없는 말로 오해 (낮을수록 좋음)", lambda s: s["missed_answers"]),
    ("e2e", "담당 기관 (기관·부서 모두)", lambda s: s["agency_and_unit"]),
    ("e2e", "전체 흐름 생활불편 유형", lambda s: s["category"]),
    ("e2e", "초안 검증 통과", lambda s: s["review_passed"]),
    ("revision", "수정 요청 반영 (문항 전체)", lambda s: (s["all_ok"], s["cases"])),
    ("revision", "요청 내용대로 고침", lambda s: s["expected"]),
]


def answer_of(part: str, got: dict) -> str:
    """회차마다 같은 답을 냈는지 비교할 핵심 답."""
    if part == "understand":
        if got["intent"] == "service":
            return f"service·{got.get('service')}"
        return f"{got['intent']}·{got['referral'] if got['intent'] == 'referral' else got['category']}"
    if part == "turn":
        return got["kind"]
    if part == "revision":
        return got["after"]["title"]
    return f"{got['category']}·{got['agency']} {got['unit']}"


def valid_part(part: str, rows: list[dict]) -> bool:
    """규칙 엔진 대체가 섞인 실행은 Claude 결과로 보지 않는다."""
    if part in ("e2e", "revision"):
        return not any(r["got"]["fallback_steps"] for r in rows)
    return all(r["source"] in ("llm", "skip") for r in rows)


def compare(paths: list[Path], data: dict) -> str:
    current = {part: {c["id"]: c for c in data[part]} for part in SCORERS}
    runs = sorted(({**json.loads(p.read_text(encoding="utf-8")), "file": p.stem} for p in paths), key=lambda r: r["file"])
    by_part: dict[str, list[tuple[str, list[dict]]]] = {}
    skipped = []
    for run in runs:
        for part, body in run["parts"].items():
            if not valid_part(part, body["rows"]):
                skipped.append(f"{run['file']}({PART_LABEL[part]})")
                continue
            rows = []
            for r in body["rows"]:
                case = current[part].get(r["id"])
                if case is None:
                    continue  # 평가 세트에서 빠진 문항
                checks = SCORERS[part](case, r)
                rows.append({**r, **case, "checks": checks, "ok": all(checks.values())})
            by_part.setdefault(part, []).append((run["file"], rows))

    n = max((len(v) for v in by_part.values()), default=0)
    lines = [f"# 흔들림 측정 ({n}회 반복)", "",
             "같은 평가 세트를 여러 번 돌려 회차마다 결과가 달라지는지 본다. 채점은 지금 평가 세트의 정답 기준으로 다시 했다.", ""]
    for part, part_runs in by_part.items():
        lines.append(f"- {PART_LABEL[part]}: " + ", ".join(f"[{f}]({f}.md)" for f, _ in part_runs))
    if skipped:
        lines.append("- 제외 (규칙 엔진 대체가 섞여 Claude 결과로 볼 수 없음): " + ", ".join(skipped))

    head = [f"{i + 1}회" for i in range(n)]
    lines += ["", "## 회차별 결과", "", "| 항목 | " + " | ".join(head) + " | 평균 |", "|---|" + "---|" * (n + 1)]
    summaries = {part: [SUMMARIZERS[part](rows) for _, rows in part_runs] for part, part_runs in by_part.items()}
    for part, label, pick in METRICS:
        if part not in summaries:
            continue
        cells = [pick(s) for s in summaries[part]]
        rates = [ok / total * 100 for ok, total in cells if total]
        avg = f"{statistics.mean(rates):.1f}%" if rates else "-"
        lines.append(f"| {label} | " + " | ".join([f"{ok}/{total}" for ok, total in cells] + ["-"] * (n - len(cells))) + f" | {avg} |")
    for part, label, key in (("understand", "문제 분석 판단 시간(초)", "seconds_avg"), ("turn", "대화 도중 판단 시간(초)", "seconds_avg"),
                             ("e2e", "전체 흐름 시간(초)", "seconds_avg"), ("revision", "수정 요청 처리 시간(초)", "seconds_avg")):
        if part in summaries:
            vals = [s[key] for s in summaries[part]]
            nums = [v for v in vals if v is not None]
            avg = f"{statistics.mean(nums):.1f}" if nums else "-"
            lines.append(f"| {label} | " + " | ".join([str(v) for v in vals] + ["-"] * (n - len(vals))) + f" | {avg} |")

    flipped, varied, always_wrong, total = [], [], [], 0
    for part, part_runs in by_part.items():
        seen: dict[str, list[dict]] = {}
        for _, rows in part_runs:
            for r in rows:
                seen.setdefault(r["id"], []).append(r)
        for cid, rs in seen.items():
            total += 1
            answers = [answer_of(part, r["got"]) for r in rs]
            oks = [r["ok"] for r in rs]
            want = rs[0]
            if part == "understand":
                truth = " · ".join(x for x in (show(want.get("intent", "")), show(want.get("category", "")), want.get("referral", "")) if x)
            elif part == "turn":
                truth = f"{want['stage']} · {want['kind']}"
            elif part == "revision":
                truth = want["kind"]
            else:
                truth = f"{want['category']} · {'/'.join(want['agency'])} {'/'.join(want['unit'])}"
            row = (f"| {PART_LABEL[part]} | {cid} | {want['text']} | {truth} | {sum(oks)}/{len(oks)} | "
                   + " / ".join(f"{a} {'✓' if ok else '✗'}" for a, ok in zip(answers, oks)) + " |")
            if len(set(oks)) > 1:
                flipped.append(row)
            elif not any(oks):
                always_wrong.append(row)
            elif len(set(answers)) > 1:
                varied.append(row)

    lines += ["", f"전체 {total}개 문항 중 회차마다 정답 여부가 달라진 문항 {len(flipped)}개, "
              f"매번 틀린 문항 {len(always_wrong)}개, 답은 달라졌지만 모두 정답인 문항 {len(varied)}개.", ""]
    table_head = ["| 구분 | ID | 입력 | 정답 | 맞은 횟수 | 회차별 답 |", "|---|---|---|---|---|---|"]
    for title, rows in (("회차마다 정답 여부가 달라진 문항", flipped), ("매번 틀린 문항", always_wrong),
                        ("답은 달라졌지만 모두 정답인 문항", varied)):
        lines += [f"## {title}", ""] + ((table_head + rows) if rows else ["없음"]) + [""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="정확도 평가 세트 실행")
    ap.add_argument("--parts", default="understand,turn", help="understand,turn,e2e,revision 중 쉼표로 (e2e·revision은 서버 필요)")
    ap.add_argument("--only", default="", help="실행할 ID (예: U01,T05,A03)")
    ap.add_argument("--base", default="http://localhost:8000", help="e2e에 쓸 서버 주소")
    ap.add_argument("--workers", type=int, default=6, help="동시에 돌릴 Claude 판단 수")
    ap.add_argument("--e2e-workers", type=int, default=3, help="동시에 돌릴 전체 흐름 수")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--compare", nargs="*", metavar="결과.json",
                    help="실행하지 않고 저장된 결과들을 비교해 흔들림 보고서를 만든다 (파일을 안 주면 docs/eval의 결과 전부)")
    args = ap.parse_args()

    if args.compare is not None:
        patterns = args.compare or [str(Path(args.out) / "*.json")]
        paths = sorted({Path(p) for pat in patterns for p in glob.glob(pat)})  # PowerShell은 *를 펼쳐 주지 않음
        if not paths:
            print("비교할 결과 파일이 없습니다.")
            return 2
        text = compare(paths, json.loads(DATASET.read_text(encoding="utf-8")))
        target = Path(args.out) / f"stability-{datetime.now().strftime('%Y%m%d-%H%M')}.md"
        target.write_bytes(text.encode("utf-8"))
        print(text)
        print(f"저장: {target}")
        return 0

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
        "revision": (lambda c: run_revision(c, args.base, data["revision_base"]), summarize_revision, args.e2e_workers),
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
