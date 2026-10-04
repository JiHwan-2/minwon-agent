"""민원 서비스 안내 (서류 발급·신고·신청): 분류 → 계획 → 위치 질문 → 가까운 기관·무인민원발급기·운영 여부 → 안내.
실제 Claude·카카오·공공데이터는 부르지 않는다 (규칙 엔진, 가짜 카카오, 가짜 공공데이터 응답)."""

import json
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from minwon import knowledge
from minwon.agent import nodes
from minwon.agent.brain import Brain
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import ServiceGuide
from minwon.api import app
from minwon.tools import kakao, kiosk, offices
from tests import fake_kakao

client = TestClient(app)

KIOSKS = [  # 카카오에서 찾은 무인민원발급기 (합성동 근처)
    {"place_name": "무인민원발급기 합성1동행정복지센터", "address_name": "경남 창원시 마산회원구 합성동 76",
     "road_address_name": "경남 창원시 마산회원구 합성동로 30", "x": "128.5868", "y": "35.2478", "distance": "120", "phone": "",
     "place_url": "http://place.map.kakao.com/1"},
    {"place_name": "마산회원구청 무인민원발급기", "address_name": "경남 창원시 마산회원구 회원동 1",
     "road_address_name": "경남 창원시 마산회원구 회원로 11", "x": "128.5700", "y": "35.2300", "distance": "1800", "phone": "",
     "place_url": "http://place.map.kakao.com/2"},
]
DATA = [  # 공공데이터 무인민원발급기 정보 (필드 이름은 공공데이터포털 명세 그대로)
    {"ISSUMCHN_NM": "합성1동 행정복지센터 무인발급기", "MNG_INST_NM": "경상남도 창원시 마산회원구",
     "INSTL_PLC_ADDR": "경상남도 창원시 마산회원구 합성동로 30", "INSTL_PLC_PSTN": "행정복지센터", "INSTL_PLC_DTL_PSTN": "1층 출입구 옆",
     "WKDY_OPER_BGNG_TM": "0700", "WKDY_OPER_END_TM": "2200", "LHLDY_OPER_BGNG_TM": "0900", "LHLDY_OPER_END_TM": "1800",
     "OPER_HR_REF_CN": "", "USE_YN_NM": "사용"},
    {"ISSUMCHN_NM": "마산회원구청 무인발급기", "MNG_INST_NM": "경상남도 창원시 마산회원구",
     "INSTL_PLC_ADDR": "경상남도 창원시 마산회원구 회원로 11", "INSTL_PLC_PSTN": "구청", "INSTL_PLC_DTL_PSTN": "민원실 앞",
     "WKDY_OPER_BGNG_TM": "00:00", "WKDY_OPER_END_TM": "24:00", "LHLDY_OPER_BGNG_TM": "00:00", "LHLDY_OPER_END_TM": "24:00",
     "OPER_HR_REF_CN": "365일 24시간", "USE_YN_NM": "사용"},
    {"ISSUMCHN_NM": "고장 난 발급기", "INSTL_PLC_ADDR": "경상남도 창원시 마산회원구 양덕로 1", "USE_YN_NM": "미사용"},
]
WEEKDAY_MORNING = datetime(2026, 10, 6, 10, 0, tzinfo=offices.KST)   # 화요일 10시
HOLIDAY_EVENING = datetime(2026, 10, 3, 19, 30, tzinfo=offices.KST)  # 토요일·개천절 19시 30분


def fake_request(path: str, params: dict, retries: int = 1):
    if path == "search/keyword.json" and params.get("query") == "무인민원발급기":
        return {"documents": KIOSKS}, 1
    return fake_kakao.request(path, params, retries)


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload, self.status_code, self.text = payload, status, json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self.payload


def data_api(rows: list[dict], seen: list[dict] | None = None):
    def get(url, params=None, timeout=None):
        if seen is not None:
            seen.append(params)
        found = rows if params.get("cond[CTPV_CD::EQ]") == "48" else []
        return FakeResponse({"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                                          "body": {"totalCount": len(found), "items": {"item": found}}}})
    return get


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):
    """가짜 카카오·공공데이터와 고정한 지금 시각."""
    monkeypatch.setattr(kakao, "request", fake_request)
    monkeypatch.setattr(kiosk, "_key", lambda: "test-key")
    monkeypatch.setattr(kiosk.httpx, "get", data_api(DATA))
    kiosk._cache.clear()

    def at(when: datetime):
        monkeypatch.setattr(offices, "current_time", lambda: when)

    at(WEEKDAY_MORNING)
    return at


def new_session() -> str:
    return client.post("/api/sessions").json()["session_id"]


def send(sid: str, text: str) -> list[dict]:
    resp = client.post(f"/api/sessions/{sid}/messages", json={"text": text})
    assert resp.status_code == 200
    return [json.loads(line) for line in resp.text.splitlines() if line]


def ended(events: list[dict]) -> list[str]:
    return [e["node"] for e in events if e["type"] == "node_end"]


def node_data(events: list[dict], node: str) -> dict:
    return next(e for e in events if e["type"] == "node_end" and e["node"] == node)["data"]


# ── 분류 ──

@pytest.mark.parametrize("text, service", [
    ("주민등록등본 어디서 뗄 수 있어요?", "resident_copy"),
    ("가족관계증명서 떼려면 어디로 가요", "family_cert"),
    ("여권 재발급은 어떻게 해요?", "passport"),
    ("이사 왔는데 전입신고 해야 돼요", "move_in"),
    ("안 쓰는 소파 버리려면 어떻게 해요?", "bulky_waste"),
    ("주민등록증 분실했어요", "id_card"),
])
def test_rule_engine_recognizes_service_questions(text, service):
    u = RuleBrain().understand(text)
    assert (u.intent, u.service) == ("service", service)


def test_complaints_stay_complaints():
    assert RuleBrain().understand("우리 골목 가로등이 일주일째 꺼져 있어요").intent == "complaint"


def test_every_service_template_is_complete():
    for code, s in knowledge.services().items():
        assert s["group"] in knowledge.service_groups(), code
        assert s["channels"] and s["summary"] and s["basis"], code
        assert set(s["needs"]) <= {"here", "residence"} and s["search_at"] in s["needs"], code
        assert all(knowledge.office_kind(kind) for kind in s["offices"]), code
        assert all(c["type"] in ("online", "kiosk", "visit", "phone") for c in s["channels"]), code
        assert any(c["type"] == "kiosk" for c in s["channels"]) == s["kiosk"], code


# ── 운영 여부 ──

def test_status_by_time_weekend_and_holiday():
    office = {"weekday": ["09:00", "18:00"], "holiday": None}
    assert offices.status(office, offices.now_info(WEEKDAY_MORNING)) == {"state": "open", "today": "09:00~18:00"}
    assert offices.status(office, offices.now_info(datetime(2026, 10, 6, 18, 0, tzinfo=offices.KST)))["state"] == "closed"
    holiday = offices.now_info(HOLIDAY_EVENING)
    assert holiday["holiday"] and not holiday["workday"]
    assert offices.status(office, holiday) == {"state": "closed", "today": "휴무"}
    assert offices.status({"weekday": ["00:00", "24:00"], "holiday": ["00:00", "24:00"]}, holiday) == {"state": "open", "today": "24시간"}
    assert offices.status({"weekday": ["09:00", "18:00"]}, holiday)["state"] == "unknown"  # 공휴일 운영을 모름
    assert offices.status(None, holiday)["state"] == "unknown"
    assert offices.now_info(datetime(2026, 10, 5, 10, 0, tzinfo=offices.KST))["holiday"]  # 개천절 대체공휴일
    assert holiday["next_workday"] == "2026-10-06(화)"  # 토요일 개천절 → 일요일 → 월요일 대체공휴일 → 화요일
    assert offices.now_info(WEEKDAY_MORNING)["next_workday"] == "2026-10-06(화)"  # 평일 18시 전이면 오늘
    assert offices.now_info(datetime(2026, 10, 8, 19, 0, tzinfo=offices.KST))["next_workday"] == "2026-10-12(월)"  # 9일 한글날


def test_office_search_keeps_only_the_offices_themselves():
    hall = knowledge.office_kind("sigungu_office")
    assert offices._keep("성산구청", hall) and offices._keep("김해시청", hall)
    assert not offices._keep("NH농협은행 성산구청 출장소", hall)  # 이름에 '구청'이 들어간 은행 지점은 빼야 한다
    assert not offices._keep("BNK경남은행 성산구청지점", hall)
    center = knowledge.office_kind("community_center")
    assert offices._keep("상남동행정복지센터", center) and not offices._keep("상남동행정복지센터 무인민원발급기", center)


def test_city_hall_is_searched_by_name_not_by_distance(monkeypatch: pytest.MonkeyPatch):
    # 가까운 순이면 '양산시청점' 가게·주차장이 먼저 나와 진짜 시청이 10개 안에 들지 못했다 (실제 카카오 결과)
    seen: list[dict] = []

    def keyword(query, size=1, **near):
        seen.append(near)
        return [{"place_name": "양산시청", "road_address_name": "경남 양산시 중앙로 39", "distance": "3703"}], 1

    monkeypatch.setattr(offices.kakao, "keyword", keyword)
    found = offices.find_offices("sigungu_office", {"x": "129.0", "y": "35.3", "sigungu": "양산시"})
    assert [p["name"] for p in found["data"]] == ["양산시청"] and seen[-1]["sort"] == "accuracy"
    offices.find_offices("community_center", {"x": "129.0", "y": "35.3", "sigungu": "양산시"})
    assert seen[-1]["sort"] == "distance"  # 행정복지센터처럼 여러 곳 중 고르는 기관은 그대로 가까운 순


def test_named_halls_count_as_specific_places():
    from minwon.tools import regions
    assert regions.is_specific_place("창원시청 근처")
    assert not regions.is_specific_place("구청 근처")


# ── 공공데이터 무인민원발급기 ──

def test_kiosk_data_is_parsed_and_cached(monkeypatch: pytest.MonkeyPatch):
    seen: list[dict] = []
    monkeypatch.setattr(kiosk, "_key", lambda: "test-key")
    monkeypatch.setattr(kiosk.httpx, "get", data_api(DATA, seen))
    kiosk._cache.clear()
    items = kiosk.installations("4812710100")
    assert [i["name"] for i in items] == ["합성1동 행정복지센터 무인발급기", "마산회원구청 무인발급기"]  # 미사용은 뺀다
    assert items[0]["hours"] == {"weekday": ["07:00", "22:00"], "holiday": ["09:00", "18:00"]}
    assert items[0]["key"] == "합성동로30" == kiosk.address_key("경남 창원시 마산회원구 합성동로 30")
    kiosk.installations("4812710100")
    assert len(seen) == 1 and seen[0]["cond[CTPV_CD::EQ]"] == "48"  # 같은 시·도는 다시 부르지 않음


def test_kiosk_api_not_registered_is_explained(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kiosk, "_key", lambda: "test-key")
    monkeypatch.setattr(kiosk.httpx, "get", lambda *a, **k: FakeResponse({"error": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}, 403))
    kiosk._cache.clear()
    with pytest.raises(kiosk.KioskDataError, match="활용신청"):
        kiosk.installations("4812710100")


# ── 전체 흐름 ──

def test_document_question_asks_location_then_finds_offices_kiosks_and_hours(world):
    sid = new_session()
    events = send(sid, "주민등록등본 어디서 뗄 수 있어요?")
    assert ended(events) == ["guard", "understand", "svc_plan", "svc_check"]
    u = node_data(events, "understand")["understanding"]
    assert (u["intent"], u["service"]) == ("service", "resident_copy")
    plan = node_data(events, "svc_plan")["plan"]
    assert [s["action"] for s in plan["steps"]] == ["service_kb", "ask_user", "geocode", "find_offices", "find_kiosks", "check_hours", "guide"]
    ask = events[-1]
    assert ask["type"] == "ask" and [q["slot"] for q in ask["questions"]] == ["here"]  # 등본은 주소지를 묻지 않는다

    events = send(sid, "창원시 마산회원구 합성동 합성초등학교 근처예요")
    assert ended(events) == ["ask", "svc_check", "locate", "svc_act", "svc_answer"]
    tools = [e["tool"] for e in events if e["type"] == "tool_start"]
    assert tools == ["geocode", "service_kb", "find_offices:community_center", "find_kiosks", "check_hours"]

    guide = events[-1]
    assert guide["type"] == "guide"
    g = guide["guide"]
    assert g["code"] == "resident_copy" and g["location"]["sigungu"] == "창원시 마산회원구"
    center = g["offices"]["community_center"][0]
    assert center["name"] == "합성1동행정복지센터" and center["state"] == "open" and center["today"] == "09:00~18:00"
    first, second = g["kiosks"]
    assert first["hours_source"] == "data_go_kr" and first["spot"] == "행정복지센터 1층 출입구 옆" and first["state"] == "open"
    assert second["today"] == "24시간"
    assert g["summary"] and g["recommendation"] and g["steps"]
    results = {e["result"]["tool"]: e["result"] for e in events if e["type"] == "tool_end"}
    assert results["find_kiosks"]["source"] == "kakao+data_go_kr"


def test_on_a_holiday_evening_closed_offices_are_not_recommended(world):
    world(HOLIDAY_EVENING)
    sid = new_session()
    send(sid, "등본 떼야 하는데")
    events = send(sid, "창원시 마산회원구 합성동 합성초등학교 근처")
    g = events[-1]["guide"]
    assert g["now"]["holiday"] and g["offices"]["community_center"][0]["state"] == "closed"
    assert [k["state"] for k in g["kiosks"]] == ["closed", "open"]  # 공휴일 09~18시 발급기는 닫혔고 24시간은 열림
    assert "마산회원구청 무인민원발급기" in g["recommendation"]  # 지금 운영 중인 곳을 먼저 알려 준다
    hours = next(e["result"] for e in events if e["type"] == "tool_end" and e["result"]["tool"] == "check_hours")
    assert "공휴일" in hours["summary"]


def test_follow_up_question_reuses_the_confirmed_location(world):
    sid = new_session()
    send(sid, "주민등록등본 어디서 뗄 수 있어요?")
    send(sid, "창원시 마산회원구 합성동 합성초등학교 근처예요")
    events = send(sid, "가족관계증명서도 떼야 돼요")
    assert ended(events) == ["guard", "understand", "svc_plan", "svc_check", "svc_act", "svc_answer"]  # 위치를 다시 묻지 않음
    assert events[-1]["guide"]["code"] == "family_cert"
    assert "앞에서 확인한 위치" in node_data(events, "svc_check")["log"][0]["detail"]
    actions = [s["action"] for s in node_data(events, "svc_plan")["plan"]["steps"]]
    assert "ask_user" not in actions and "geocode" not in actions  # 계획에도 위치 확인 단계가 없다


def test_move_in_asks_the_new_address_and_searches_there(world):
    sid = new_session()
    events = send(sid, "이사 왔는데 전입신고 해야 돼요")
    ask = events[-1]
    assert [q["slot"] for q in ask["questions"]] == ["residence"]
    assert "주민등록 주소지" in ask["questions"][0]["text"]
    events = send(sid, "창원시 마산회원구 합성동 합성초등학교 앞 아파트")
    g = events[-1]["guide"]
    assert g["deadline"].startswith("이사한 날부터 14일") and g["kiosks"] == []  # 전입신고는 발급기로 안 됨
    assert g["offices"]["community_center"]


def test_vague_place_is_asked_once_more(world):
    sid = new_session()
    send(sid, "등본 어디서 떼요")
    events = send(sid, "우리 동네요")
    assert ended(events) == ["ask", "svc_check"]
    assert "'우리 동네요'만으로는" in events[-1]["questions"][0]["text"]
    events = send(sid, "모름")
    assert events[-1]["type"] == "guide"  # 끝내 모르면 온라인 방법 위주로 안내
    assert events[-1]["guide"]["location"] is None


def test_kiosk_data_unavailable_still_lists_nearby_kiosks(world, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kiosk.httpx, "get", lambda *a, **k: FakeResponse({"error": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}, 403))
    sid = new_session()
    send(sid, "등본 어디서 떼요")
    events = send(sid, "창원시 마산회원구 합성동 합성초등학교 근처")
    result = next(e["result"] for e in events if e["type"] == "tool_end" and e["result"]["tool"] == "find_kiosks")
    assert result["ok"] and result["source"] == "kakao" and "활용신청" in result["error"]
    assert [k["state"] for k in events[-1]["guide"]["kiosks"]] == ["unknown", "unknown"]


def test_made_up_contacts_in_the_guide_are_replaced(world, monkeypatch: pytest.MonkeyPatch):
    class Inventive(RuleBrain):
        def service_guide(self, ctx):
            return ServiceGuide(summary="02-123-4567로 전화하세요.", recommendation="www.example.com에서 받으세요.", steps=["가세요"], tips=[])

    monkeypatch.setattr(nodes, "get_brain", lambda: Brain(Inventive()))
    sid = new_session()
    send(sid, "등본 어디서 떼요")
    events = send(sid, "창원시 마산회원구 합성동 합성초등학교 근처")
    g = events[-1]["guide"]
    assert g["guarded"] and "02-123-4567" not in g["summary"]
    assert node_data(events, "svc_answer")["log"][0]["source"] == "rule_fallback"


def test_service_without_a_known_code_asks_what_they_want(monkeypatch: pytest.MonkeyPatch):
    class Unsure(RuleBrain):
        def understand(self, text):
            return super().understand(text).model_copy(update={"intent": "service", "service": "none", "category": "other"})

    monkeypatch.setattr(nodes, "get_brain", lambda: Brain(Unsure()))
    events = send(new_session(), "동사무소 몇 시까지 해요?")
    assert node_data(events, "understand")["understanding"]["intent"] == "unclear"
    assert events[-1]["type"] == "redirect"
