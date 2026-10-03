"""다국어: 외국인 시민은 대화·안내를 자기 언어로 받고, 민원 초안은 한국어 원문 + 번역본으로 받는다."""

import re
import string

import pytest

from minwon import i18n, knowledge
from minwon.agent import brain as brain_module
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import Translation
from tests.test_agent_flow import client, ended_nodes, new_session, send

NOISE = "창원시 성산구 상남동 상가 공사 소음이 매일 아침 7시부터 심해요"


def _tr(text: str) -> str:
    return f"[vi] {text}" if text else text


class SpeaksVietnamese(RuleBrain):
    """언어 판단·번역만 정해 둔 가짜 Claude: 시민이 베트남어를 쓴다고 보고, 번역은 앞에 [vi]를 붙인다 (나머지는 규칙 엔진)."""

    def __init__(self, evidence_cut: int = 0):
        super().__init__()
        self.contexts: dict[str, dict] = {}
        self.evidence_cut = evidence_cut

    def understand(self, text):
        return super().understand(text).model_copy(update={"language": "vi"})

    def plan(self, ctx):
        self.contexts["plan"] = ctx
        return super().plan(ctx)

    def check(self, ctx):
        self.contexts["check"] = ctx
        return super().check(ctx)

    def translate(self, ctx):
        self.contexts["translate"] = ctx
        src = ctx["source"]
        evidence = [{k: _tr(v) for k, v in e.items()} for e in src["evidence"]]
        return Translation(
            title=_tr(src["title"]), body=_tr(src["body"]),
            evidence=evidence[: len(evidence) - self.evidence_cut],
            tips=[_tr(x) for x in src["tips"]], reason=_tr(src["reason"]), steps=[_tr(x) for x in src["steps"]],
            cautions=[_tr(x) for x in src["cautions"]], issues=[_tr(x) for x in src["issues"]],
            unit=_tr(src["unit"]), duty=_tr(src["duty"]), period=_tr(src["period"]),
        )


class CannotTranslate(SpeaksVietnamese):
    def translate(self, ctx):
        raise TimeoutError("Claude 응답 없음")


class RefersInVietnamese(SpeaksVietnamese):
    def understand(self, text):
        return super().understand(text).model_copy(update={"intent": "referral", "referral": "consumer", "category": "other"})


def _use(monkeypatch, primary):
    brain = brain_module.Brain(primary)
    monkeypatch.setattr("minwon.agent.nodes.get_brain", lambda: brain)
    monkeypatch.setattr("minwon.agent.topic.get_brain", lambda: brain)
    return primary


def _finish(sid: str, first: str) -> list[dict]:
    events = send(sid, first)
    while events[-1]["type"] == "ask":
        events = send(sid, "모름")
    return events


# ---- 흐름 ----

def test_foreign_citizen_gets_translation_and_korean_original(monkeypatch: pytest.MonkeyPatch):
    fake = _use(monkeypatch, SpeaksVietnamese())
    sid = new_session()
    events = _finish(sid, NOISE)
    nodes = ended_nodes(events)
    assert nodes[-3:] == ["review", "translate", "deliver"]  # 검증을 마친 한국어 초안을 번역한 뒤 결과물 만들기
    assert fake.contexts["plan"]["language"] == fake.contexts["check"]["language"] == "vi"  # 대화 문장은 시민의 언어로

    ready = events[-1]
    pkg, tr = ready["package"], ready["translation"]
    assert not pkg["title"].startswith("[vi]")  # 제출용 원문은 한국어 그대로
    assert tr["language"] == "vi" and tr["translated"] and tr["version"] == pkg["version"]
    assert tr["title"] == _tr(pkg["title"]) and tr["body"] == _tr(pkg["body"])
    assert len(tr["evidence"]) == len(pkg["evidence"]) and tr["steps"] == [_tr(s) for s in ready["decision"]["steps"]]
    assert fake.contexts["translate"]["source"]["title"] == pkg["title"]
    assert ready["files"]["pdf"]["name"]  # PDF는 한국어 원문으로 만든다


def test_korean_citizen_skips_translation():
    events = _finish(new_session(), NOISE)
    assert "translate" not in ended_nodes(events)
    assert events[-1]["translation"] is None


def test_revision_is_translated_again(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, SpeaksVietnamese())
    sid = new_session()
    first = _finish(sid, NOISE)[-1]
    events = send(sid, "더 짧게 써 주세요")
    assert ended_nodes(events)[-2:] == ["translate", "deliver"]
    assert events[-1]["translation"]["version"] == first["package"]["version"] + 1


def test_translation_failure_shows_korean(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, CannotTranslate())
    ready = _finish(new_session(), NOISE)[-1]
    tr = ready["translation"]
    assert not tr["translated"] and tr["title"] == ready["package"]["title"]  # 번역 대신 한국어 그대로 보여 줌


def test_list_with_wrong_length_keeps_korean(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, SpeaksVietnamese(evidence_cut=1))
    sid = new_session()
    ready = _finish(sid, NOISE)[-1]
    tr = ready["translation"]
    assert [e["item"] for e in tr["evidence"]] == [e["item"] for e in ready["package"]["evidence"]]  # 어느 항목인지 알 수 없어 원문 유지
    assert tr["title"].startswith("[vi]")
    log = next(x for x in client.get(f"/api/sessions/{sid}").json()["log"] if x["node"] == "translate")
    assert "evidence" in log["detail"]


def test_referral_card_in_citizen_language(monkeypatch: pytest.MonkeyPatch):
    _use(monkeypatch, RefersInVietnamese())
    last = send(new_session(), "Hàng giao đã 3 ngày mà vẫn chưa đến")[-1]
    ref = last["referral"]
    assert ref["phone"] == "1372" and ref["url"] == "https://www.ccn.go.kr"  # 번호·주소는 원문
    assert ref["agency"] == i18n.REFERRALS["consumer"]["vi"]["agency"]
    assert last["message"] == i18n.t("referral.reply", "vi", label=ref["label"], agency=ref["agency"], first=ref["first"])


def test_crisis_notice_in_the_language_it_was_written():
    events = send(new_session(), "Dạo này tôi mệt mỏi quá, tôi muốn chết")
    assert events[0] == {"type": "crisis", "message": i18n.t("crisis.notice", "vi")}


def test_latin_text_uses_screen_language_when_claude_fails(monkeypatch: pytest.MonkeyPatch):
    class FailsToUnderstand(RuleBrain):
        def understand(self, text):
            raise TimeoutError("Claude 응답 없음")

    _use(monkeypatch, FailsToUnderstand())
    sid = new_session()
    resp = client.post(f"/api/sessions/{sid}/messages", json={"text": "Lampu jalan di gang rumah saya mati", "lang": "id"})
    assert resp.status_code == 200
    assert client.get(f"/api/sessions/{sid}").json()["understanding"]["language"] == "id"


# ---- 번역 자료 ----

def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_fixed_text_has_all_languages_with_same_blanks():
    for key, texts in i18n.TEXT.items():
        assert set(texts) == set(i18n.LANGS), key
        assert len({frozenset(_fields(t)) for t in texts.values()}) == 1, key  # 언어마다 같은 {칸}


def test_every_referral_has_all_translations():
    assert set(i18n.REFERRALS) == set(knowledge.referrals())
    for code, langs in i18n.REFERRALS.items():
        assert set(langs) == set(i18n.LANGS) - {"ko"}, code
        for lang, fields in langs.items():
            assert {"label", "agency", "operator", "hours", "first"} <= set(fields), (code, lang)
            assert re.search(r"[가-힣]", fields["agency"]), (code, lang)  # 한국어 기관 이름을 남겨 찾을 수 있게
        card = knowledge.referral(code, "ja")
        assert card["url"] == knowledge.referrals()[code]["url"]  # 주소는 번역하지 않음


def test_language_detection_and_fallback():
    assert i18n.detect("가로등이 꺼졌어요") == "ko"
    assert i18n.detect("街灯が消えています") == "ja"
    assert i18n.detect("路灯坏了") == "zh"
    assert i18n.detect("ไฟถนนดับ") == "th"
    assert i18n.detect("Đèn đường bị tắt") == "vi"
    assert i18n.detect("Lampu jalan mati") is None  # 라틴 문자는 글자 모양만으로 알 수 없음
    assert i18n.ui_lang("zh-CN") == "zh" and i18n.ui_lang("fr") == "en" and i18n.ui_lang("") == "ko"
    assert i18n.t("cancelled", "fr") == i18n.TEXT["cancelled"]["en"]  # 번역해 두지 않은 언어는 영어 안내문
