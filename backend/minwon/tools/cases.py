"""비슷한 민원 사례 조회: 국민권익위원회 민원정책 질의응답(공공데이터포털 Open API)에서 같은 유형의 사례를 찾는다."""

import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import unquote, urlencode

import httpx

from minwon import knowledge
from minwon.settings import settings
from minwon.tools import regions, tool_result

URL = "https://apis.data.go.kr/1140100/CivilPolicyQnaService/PolicyQnaList"
DETAIL_URL = "https://www.epeople.go.kr/nep/pttn/gnrlPttn/pttnSmlrCaseDetail.npaid"  # 국민신문고 사례 원문 (질문·답변·담당부서)
SOURCE_NAME = "국민권익위원회 민원정책 질의응답 (공공데이터포털)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_QUERIES = 3
MAX_CASES = 3
NO_DATA_CODES = {"E03"}

# 공공데이터포털 게이트웨이 오류 코드 → 사용자에게 보여 줄 설명
GATEWAY_ERRORS = {
    "SERVICE_KEY_IS_NULL": "공공데이터 서비스키가 비어 있습니다",
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR": "등록되지 않은 공공데이터 서비스키입니다 (활용신청 직후라면 잠시 뒤 다시 시도)",
    "SERVICE_ACCESS_DENIED_ERROR": "이 API의 활용신청이 승인되지 않았습니다",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR": "공공데이터 API 하루 호출 한도를 넘었습니다",
    "DEADLINE_HAS_EXPIRED_ERROR": "공공데이터 활용 기간이 끝났습니다",
}


class DataGoKrError(Exception):
    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


def service_key() -> str:
    key = settings.data_go_kr_service_key.strip()
    return unquote(key) if "%" in key else key  # 포털의 Encoding 키를 넣어도 동작


def _parse(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        try:
            return ET.fromstring(resp.text)
        except ET.ParseError:
            return None


def _gateway_error(data: Any) -> str:
    if isinstance(data, dict):
        header = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {})
        return header.get("errMsg", "") if header else ""
    if isinstance(data, ET.Element):
        node = data.find(".//errMsg")
        return (node.text or "").strip() if node is not None else ""
    return ""


def _request(query: str, retries: int = 1) -> tuple[Any, int]:
    attempts = 0
    while True:
        attempts += 1
        try:
            resp = httpx.get(URL, params={
                "serviceKey": service_key(), "firstIndex": 1, "recordCountPerPage": 20,  # 지역 우선 정렬용으로 넉넉히
                "keyword": query, "searchType": 1,  # 1 = 제목에서 검색
            }, timeout=6.0)
            data = _parse(resp)
            error = _gateway_error(data)
            if resp.status_code == 200 and not error and data is not None:
                return data, attempts
            if resp.status_code not in RETRYABLE_STATUS or attempts > retries:
                message = GATEWAY_ERRORS.get(error) or (f"공공데이터 API 오류 ({error})" if error else f"공공데이터 API 오류 (HTTP {resp.status_code})")
                raise DataGoKrError(message, attempts)
        except httpx.TransportError as e:
            if attempts > retries:
                raise DataGoKrError(f"공공데이터 API 연결 실패 ({type(e).__name__})", attempts) from e
        time.sleep(0.4)


def _rows(data: Any) -> list[dict]:
    """응답 감싸기 모양에 상관없이 제목(title)이 있는 항목 목록을 찾는다 (JSON·XML 모두)."""
    if isinstance(data, ET.Element):
        return [{child.tag: (child.text or "").strip() for child in el} for el in data.iter() if el.find("title") is not None]
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data) and any("title" in x for x in data):
            return data
        return [row for x in data for row in _rows(x)]
    if isinstance(data, dict):
        if "title" in data and not any(isinstance(v, (dict, list)) for v in data.values()):
            return [data]  # 결과가 1건이면 목록 대신 항목 하나로 오는 경우
        return [row for v in data.values() if isinstance(v, (dict, list)) for row in _rows(v)]
    return []


def _total(data: Any, rows: list[dict]) -> int:
    raw = None
    if isinstance(data, dict):
        stack = [data]
        while stack and raw is None:
            node = stack.pop()
            raw = node.get("resultCount")
            stack += [v for v in node.values() if isinstance(v, dict)]
    elif isinstance(data, ET.Element):
        node = data.find(".//resultCount")
        raw = node.text if node is not None else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return len(rows)


def _result_error(data: Any) -> str:
    """API 자체 결과코드가 실패(S로 시작하지 않음)면 메시지를 돌려준다."""
    if isinstance(data, dict):
        code, message = str(data.get("resultCode", "S")), data.get("resultMessage", "")
    elif isinstance(data, ET.Element):
        code_el, msg_el = data.find(".//resultCode"), data.find(".//resultMessage")
        code = (code_el.text or "S") if code_el is not None else "S"
        message = (msg_el.text or "") if msg_el is not None else ""
    else:
        return ""
    if code.startswith("S") or code in NO_DATA_CODES:
        return ""  # E03 '조회된 데이터가 없습니다'는 결과 0건 → 다음 검색어로
    return f"공공데이터 API 결과 오류 ({code} {message})".strip()


def case_url(faq_no: str, duty: str) -> str:
    """국민신문고 '민원 질의응답·답변원문'의 그 사례 원문 주소. 번호·업무구분이 정상 값일 때만 만든다 (외부 데이터로 이상한 주소를 만들지 않게)."""
    if not (re.fullmatch(r"\d{1,16}", faq_no) and re.fullmatch(r"[a-z]{1,10}", duty)):
        return ""
    return f"{DETAIL_URL}?{urlencode({'epUnionSn': faq_no, 'dutySctnNm': duty})}"


def _case(row: dict) -> dict:
    date = str(row.get("regDate", ""))
    faq_no, duty = str(row.get("faqNo", "")).strip(), str(row.get("dutySctnNm", "")).strip()
    return {
        "title": str(row.get("title", "")).strip(),
        "agency": str(row.get("ancName", "")).strip(),
        "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) >= 8 and date[:8].isdigit() else "",
        "id": faq_no,
        "url": case_url(faq_no, duty),
    }


def _local_first(items: list[dict], location: dict) -> tuple[list[dict], str]:
    """사용자 위치와 같은 시·군 → 같은 시·도 처리기관 사례를 앞으로 (순서는 그대로 유지). (정렬 결과, 일치한 지역)"""
    city, sido = regions.city_name(location.get("sigungu", "")), location.get("sido", "")

    def score(case: dict) -> int:
        return 2 if city and city in case["agency"] else 1 if sido and sido in case["agency"] else 0

    ranked = sorted(items, key=score, reverse=True)
    best = score(ranked[0]) if ranked else 0
    return ranked, {2: city, 1: sido}.get(best, "")


def queries(category: str, keywords: list[str]) -> list[str]:
    """유형별 대표 검색어를 먼저, 그다음 AI가 뽑은 핵심어를 쓴다 (짧은 명사가 제목 검색에 잘 걸림)."""
    terms = [*knowledge.agency_rules(category).get("case_terms", []), *keywords]
    return list(dict.fromkeys(t.strip() for t in terms if t and t.strip()))[:MAX_QUERIES]


def similar_cases(category: str, keywords: list[str], location: dict | None = None) -> dict:
    tried = queries(category, keywords)
    data = {"queries": tried, "query": "", "total": 0, "items": [], "local": "", "source_name": SOURCE_NAME}
    if not service_key():
        return tool_result("case_search", False, "skipped", "공공데이터 서비스키가 없어 사례 조회를 건너뜀", data,
                           error="공공데이터 서비스키가 설정되지 않았습니다")
    if not tried:
        return tool_result("case_search", False, "skipped", "검색어가 없어 사례 조회를 건너뜀", data)

    retries = 0
    try:
        for query in tried:
            raw, attempts = _request(query)
            retries += attempts - 1
            if error := _result_error(raw):
                raise DataGoKrError(error, attempts)
            rows = [r for r in (_case(x) for x in _rows(raw)) if r["title"]]
            if rows:
                ranked, local = _local_first(rows, location or {})
                data |= {"query": query, "total": _total(raw, rows), "items": ranked[:MAX_CASES], "local": local}
                break
    except DataGoKrError as e:
        return tool_result("case_search", False, "error", "사례 조회 실패 → 사례 없이 진행", data,
                           retries=retries + max(e.attempts - 1, 0), error=str(e))

    if not data["items"]:
        return tool_result("case_search", True, "data_go_kr", f"'{', '.join(tried)}' 관련 공개 사례 없음", data, retries=retries)
    first = data["items"][0]
    summary = f"'{data['query']}' 관련 사례 {data['total']}건 중 {len(data['items'])}건"
    if data["local"]:
        summary += f" ({data['local']} 사례 우선)"
    summary += f" · 예: {first['title']}"
    if first["agency"]:
        summary += f" ({first['agency']})"
    return tool_result("case_search", True, "data_go_kr", summary, data, retries=retries)
