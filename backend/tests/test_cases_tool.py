"""비슷한 민원 사례 조회(공공데이터포털): 실제 API 대신 가짜 응답으로 검색·해석·오류 처리를 확인한다."""

import dataclasses
import json

import httpx
import pytest

from minwon.tools import cases

ROWS = [
    {"faqNo": 1001, "title": "보안등 고장 신고는 어디에 하나요", "ancName": "창원시", "regDate": "20240312101500", "dutySctnNm": "민원"},
    {"faqNo": 1002, "title": "골목 보안등 수리 요청", "ancName": "김해시", "regDate": "20231105090000", "dutySctnNm": "민원"},
]


def _json(status: int, payload) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(payload, ensure_ascii=False).encode(), headers={"content-type": "application/json"})


class FakeApi:
    """httpx.get 대신 불려서 받은 파라미터를 기록하고, 정해 둔 응답을 차례로 돌려준다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.params: list[dict] = []

    def __call__(self, url, params=None, timeout=None):
        assert url == cases.URL
        self.params.append(params)
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cases, "settings", dataclasses.replace(cases.settings, data_go_kr_service_key="test-key"))
    monkeypatch.setattr(cases.time, "sleep", lambda _s: None)

    def install(*responses):
        fake = FakeApi(*responses)
        monkeypatch.setattr(cases.httpx, "get", fake)
        return fake

    return install


def test_without_key_skips_and_explains():
    r = cases.similar_cases("street_light", ["가로등"])
    assert not r["ok"] and r["source"] == "skipped"
    assert "서비스키" in r["error"] and r["data"]["items"] == []


def test_queries_use_category_terms_first_then_ai_keywords():
    assert cases.queries("street_light", ["가로등 고장", "골목"]) == ["가로등", "보안등", "가로등 고장"]
    assert cases.queries("other", ["  ", "버스킹 소음"]) == ["버스킹 소음"]


def test_finds_cases_and_tries_next_query_when_empty(api):
    fake = api(
        _json(200, {"resultCode": "S00", "resultMessage": "0(건) 조회되었습니다", "resultCount": 0, "resultList": []}),
        _json(200, {"resultCode": "S00", "resultMessage": "2(건) 조회되었습니다", "resultCount": 2, "resultList": ROWS}),
    )
    r = cases.similar_cases("street_light", [])
    assert r["ok"] and r["source"] == "data_go_kr"
    assert [p["keyword"] for p in fake.params] == ["가로등", "보안등"]
    assert fake.params[0]["serviceKey"] == "test-key" and fake.params[0]["searchType"] == 1
    data = r["data"]
    assert data["query"] == "보안등" and data["total"] == 2
    assert data["items"][0] == {"title": "보안등 고장 신고는 어디에 하나요", "agency": "창원시", "date": "2024-03-12", "id": "1001"}
    assert "사례 2건 중 2건" in r["summary"] and "(창원시)" in r["summary"]


def test_reads_nested_and_xml_responses(api):
    api(_json(200, {"response": {"body": {"items": {"item": ROWS[0]}}, "resultCount": 1}}))
    assert cases.similar_cases("street_light", [])["data"]["items"][0]["agency"] == "창원시"

    xml = ("<response><resultCode>S00</resultCode><resultCount>1</resultCount><resultList>"
           "<item><faqNo>7</faqNo><title>보안등 점검 요청</title><ancName>진주시</ancName><regDate>20250101000000</regDate></item>"
           "</resultList></response>")
    api(httpx.Response(200, content=xml.encode(), headers={"content-type": "application/xml"}))
    item = cases.similar_cases("street_light", [])["data"]["items"][0]
    assert item["title"] == "보안등 점검 요청" and item["date"] == "2025-01-01"


def test_no_cases_anywhere_is_not_an_error(api):
    empty = {"resultCode": "S00", "resultCount": 0, "resultList": []}
    api(_json(200, empty), _json(200, empty), _json(200, empty))
    r = cases.similar_cases("street_light", ["가로등 고장"])
    assert r["ok"] and r["data"]["items"] == [] and "공개 사례 없음" in r["summary"]


def test_gateway_error_is_explained_without_retry(api):
    fake = api(_json(403, {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
        "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnAuthMsg": "등록되지 않은 서비스키", "returnReasonCode": "30"}}}))
    r = cases.similar_cases("street_light", [])
    assert not r["ok"] and r["source"] == "error"
    assert "등록되지 않은 공공데이터 서비스키" in r["error"] and len(fake.params) == 1


def test_temporary_error_is_retried_once(api):
    fake = api(httpx.ConnectTimeout("timeout"), _json(200, {"resultCode": "S00", "resultCount": 2, "resultList": ROWS}))
    r = cases.similar_cases("street_light", [])
    assert r["ok"] and r["retries"] == 1 and len(fake.params) == 2


def test_api_result_code_failure_is_reported(api):
    api(_json(200, {"resultCode": "E99", "resultMessage": "검색 오류"}))
    r = cases.similar_cases("street_light", [])
    assert not r["ok"] and "E99" in r["error"]


def test_encoded_key_from_portal_is_decoded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cases, "settings", dataclasses.replace(cases.settings, data_go_kr_service_key="ab%2Bcd%3D%3D"))
    assert cases.service_key() == "ab+cd=="


def test_cases_from_users_region_come_first(api):
    rows = [
        {"faqNo": 1, "title": "가로등 미점등", "ancName": "경기도 수원시", "regDate": "20260729000000"},
        {"faqNo": 2, "title": "가로등 고장 신고", "ancName": "경상남도 고성군", "regDate": "20260730000000"},
        {"faqNo": 3, "title": "보안등 수리", "ancName": "경상남도 창원시", "regDate": "20250101000000"},
    ]
    api(_json(200, {"resultCode": "S00", "resultCount": "3", "resultList": rows}))
    r = cases.similar_cases("street_light", [], {"sido": "경상남도", "sigungu": "창원시 마산회원구"})
    assert [c["agency"] for c in r["data"]["items"]] == ["경상남도 창원시", "경상남도 고성군", "경기도 수원시"]
    assert r["data"]["local"] == "창원시" and r["data"]["total"] == 3 and "(창원시 사례 우선)" in r["summary"]


def test_no_data_code_moves_on_to_next_query(api):
    fake = api(
        _json(200, {"resultCode": "E03", "resultMessage": "조회된 데이터가 없습니다."}),
        _json(200, {"resultCode": "S00", "resultCount": "2", "resultList": ROWS}),
    )
    r = cases.similar_cases("street_light", [])
    assert r["ok"] and len(fake.params) == 2 and r["data"]["query"] == "보안등"

    empty = {"resultCode": "E03", "resultMessage": "조회된 데이터가 없습니다."}
    api(_json(200, empty), _json(200, empty))
    r = cases.similar_cases("other", ["컨테이너", "공터"])
    assert r["ok"] and r["data"]["items"] == [] and "공개 사례 없음" in r["summary"]
