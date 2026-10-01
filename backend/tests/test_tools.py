import httpx
import pytest

from minwon.agent.nodes import _normalize_plan
from minwon import knowledge
from minwon.tools import kakao
from minwon.tools.kb import kb_lookup
from minwon.tools.locate import find_nearby, geocode
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
    assert actions == ["geocode", "find_nearby", "kb_lookup", "write", "review"]
    assert "police" in fixed["nearby_kinds"] and "location" in fixed["required_info"]
    assert len(fixes) >= 4
