import httpx
import pytest

from minwon.agent.nodes import _normalize_plan
from minwon import knowledge
from minwon.tools import kakao, regions
from minwon.tools.kb import kb_lookup
from minwon.tools.locate import find_nearby, geocode, resolve_candidate
from tests import fake_kakao


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)


def test_geocode_with_kakao_returns_admin_region(fake):
    r = geocode("창원 합성초등학교")
    assert r["ok"] and r["source"] == "kakao"
    loc = r["data"]
    assert loc["sigungu"] == "창원시 마산회원구"
    assert loc["dong"] == "합성1동" and loc["legal_dong"] == "합성동"
    assert loc["address"] == "경남 창원시 마산회원구 합성동로 30"
    assert r["retries"] == 0


@pytest.mark.parametrize(
    ("text", "specific"),
    [
        ("창원 초등학교 정문 앞", False),
        ("우리 아파트 앞", False),
        ("학교 앞", False),
        ("창원", False),
        ("합성초등학교 앞", True),
        ("창원초등학교에서", True),
        ("마산회원구 합성동 골목", True),
        ("합성북16길 75", True),
        ("어린이보호구역 근처", False),
    ],
)
def test_place_specificity(text, specific):
    assert regions.is_specific_place(text) is specific


def test_vague_place_returns_candidates_inside_named_city(fake):
    r = geocode("창원 초등학교")
    loc = r["data"]
    assert loc["ambiguous"]
    assert [c["name"] for c in loc["candidates"]] == ["창원초등학교", "합성초등학교", "상남초등학교"]
    assert "사용자 확인 필요" in r["summary"]


def test_specific_place_is_not_ambiguous(fake):
    loc = geocode("창원 합성초등학교")["data"]
    assert not loc["ambiguous"] and loc["place_name"] == "합성초등학교"


def test_resolve_candidate_uses_its_own_region(fake):
    picked = geocode("창원 초등학교")["data"]["candidates"][2]
    loc = resolve_candidate(picked, "창원 초등학교")["data"]
    assert loc["place_name"] == "상남초등학교" and loc["sigungu"] == "창원시 성산구"


def test_geocode_falls_back_to_text_when_kakao_fails(monkeypatch):
    def broken(*_a, **_k):
        raise kakao.KakaoError("카카오 API 연결 실패 (ConnectTimeout)", attempts=2)

    monkeypatch.setattr(kakao, "request", broken)
    r = geocode("마산회원구 합성초등학교 앞", "창원 합성동 학교 앞이 위험해요")
    assert r["ok"] and r["source"] == "text_fallback"
    assert r["data"]["sigungu"] == "창원시 마산회원구"
    assert r["retries"] == 1 and "ConnectTimeout" in r["error"]


def test_geocode_without_api_key_uses_text(monkeypatch):
    monkeypatch.setattr(kakao, "api_key", lambda: "")
    r = geocode("통영시 무전동 공원")
    assert r["source"] == "text_fallback" and r["data"]["sigungu"] == "통영시"
    assert "키가 설정되지 않았습니다" in r["error"]


def test_geocode_reports_failure_when_no_region_anywhere(monkeypatch):
    monkeypatch.setattr(kakao, "api_key", lambda: "")
    r = geocode("", "집 앞이 시끄러워요")
    assert not r["ok"]


def test_kakao_retries_transient_errors_but_not_auth_errors(monkeypatch):
    monkeypatch.setattr(kakao, "api_key", lambda: "test-key")
    monkeypatch.setattr(kakao.time, "sleep", lambda _s: None)
    calls = []

    def flaky(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json={"documents": []})

    monkeypatch.setattr(kakao.httpx, "get", flaky)
    _, attempts = kakao.request("search/keyword.json", {"query": "x"})
    assert attempts == 2

    monkeypatch.setattr(kakao.httpx, "get", lambda *_a, **_k: httpx.Response(403, json={}))
    with pytest.raises(kakao.KakaoError) as err:
        kakao.request("search/keyword.json", {"query": "x"})
    assert err.value.attempts == 1 and "카카오맵" in str(err.value)


def test_find_nearby_police_skips_substations(fake):
    loc = geocode("창원 합성초등학교")["data"]
    r = find_nearby("police", loc)
    assert r["ok"] and r["data"][0]["name"] == "마산동부경찰서"
    assert all(p["name"].endswith("경찰서") for p in r["data"])


def test_find_nearby_is_skipped_without_coordinates():
    r = find_nearby("police", {"sigungu": "통영시"})
    assert not r["ok"] and r["source"] == "skipped"


def test_kb_lookup_resolves_real_agencies(fake):
    loc = geocode("창원 합성초등학교")["data"]
    nearby = {"police": find_nearby("police", loc)["data"]}
    r = kb_lookup("traffic_safety", loc, nearby)
    agencies = [d["agency"] for d in r["data"]["departments"]]
    assert agencies == ["창원시 마산회원구청", "마산동부경찰서"]
    assert r["data"]["channels"][0]["name"] == "안전신문고"

    center = {"community_center": find_nearby("community_center", loc)["data"]}
    street = kb_lookup("street_light", loc, center)["data"]["departments"]
    assert street[0]["agency"] == "합성1동행정복지센터"

    bus = kb_lookup("public_transport", loc, {})["data"]["departments"]
    assert bus[0]["agency"] == "창원시청"


def test_kb_lookup_without_location_gives_general_guidance():
    r = kb_lookup("traffic_safety", {}, {})
    assert [d["agency"] for d in r["data"]["departments"]] == ["관할 시·군·구청", "관할 경찰서"]


def test_plan_normalization_adds_missing_tool_steps():
    plan = {"goal": "g", "required_info": ["detail"], "nearby_kinds": [],
            "steps": [{"action": "write", "title": "작성", "reason": "r"}]}
    fixed, fixes = _normalize_plan(plan, knowledge.category("traffic_safety"))
    actions = [s["action"] for s in fixed["steps"]]
    assert actions == ["geocode", "find_nearby", "kb_lookup", "case_search", "write", "review", "deliver"]
    assert "police" in fixed["nearby_kinds"] and "location" in fixed["required_info"]
    assert len(fixes) >= 4


def test_community_center_search_skips_unmanned_kiosk(monkeypatch: pytest.MonkeyPatch):
    docs = [
        {"place_name": "무인민원발급창구 합성1동행정복지센터", "road_address_name": "경남 창원시 마산회원구 합성북16길 1", "distance": "120"},
        {"place_name": "합성1동행정복지센터", "road_address_name": "경남 창원시 마산회원구 합성북16길 1", "phone": "055-000-0000", "distance": "125"},
    ]
    monkeypatch.setattr(kakao, "keyword", lambda *a, **k: (docs, 1))
    r = find_nearby("community_center", {"x": "128.58", "y": "35.24", "sigungu": "창원시 마산회원구", "dong": "합성1동"})
    assert r["ok"] and [p["name"] for p in r["data"]] == ["합성1동행정복지센터"]


@pytest.mark.parametrize(("text", "sido"), [
    ("제 번호는 [휴대전화번호 가림]이고 창원시 성산구 상남동 공사장이 시끄러워요", "경상남도"),  # '휴대전화'의 '대전'은 시·도가 아님
    ("서울시 강남구 역삼동 가로등이 꺼졌어요", "서울특별시"),
    ("경남 김해시 내동 횡단보도", "경상남도"),
    ("강원 고성군 거진읍 도로가 파였어요", "강원특별자치도"),
])
def test_region_parse_matches_province_only_at_word_start(text, sido):
    assert regions.parse(text)["sido"] == sido


def test_geocode_retries_with_area_when_place_is_not_on_map(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    r = geocode("창원시 성산구 상남동 공사장", "새벽 5시부터 공사장 소음이 심해요")
    assert r["ok"] and r["source"] == "kakao" and "동 단위로 확인" in r["summary"]
    assert r["data"]["sigungu"] == "창원시 성산구" and r["data"]["dong"] == "상남동" and r["data"]["x"] == "128.6900"
    assert r["data"]["approximate"] and r["error"] == "카카오 검색 결과 없음"
