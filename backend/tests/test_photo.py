"""현장 사진 첨부: 사진 정보(EXIF)의 촬영 위치·시각 읽기, 사진 분석 → 예/아니요 확인 → 민원 흐름.
사진을 보는 Claude는 정해 둔 분석을 돌려주는 가짜로 바꾸고, 나머지 단계는 규칙 엔진·가짜 카카오로 확인한다."""

import base64
import dataclasses
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, TiffImagePlugin

from minwon.agent import brain as brain_module
from minwon.agent import nodes
from minwon.agent.brain import Brain, ClaudeCodeBrain
from minwon.agent.rules import RuleBrain
from minwon.agent.schemas import PhotoAnalysis
from minwon.api import app
from minwon.tools import kakao, photo
from tests import fake_kakao
from tests.test_claude_code_brain import FakeClaude

client = TestClient(app)
R = TiffImagePlugin.IFDRational

SIDEWALK = {
    "relevant": True,
    "scene": "인도 보도블록 여러 장이 깨져 들떠 있습니다.",
    "issue": "인도 보도블록이 깨지고 들떠 있어 걷다가 걸려 넘어질 수 있어요.",
    "question": "인도 보도블록이 깨져 있어 걷기 위험한 게 불편하신가요?",
    "category": "road_damage",
    "emergency": False,
    "location_clues": "",
}


def jpeg(gps: tuple[float, float] | None = None, taken: str = "", size=(800, 600)) -> bytes:
    """GPS(위도, 경도)·촬영 시각을 EXIF에 넣은 JPEG."""
    exif = Image.Exif()
    if gps:
        def dms(value: float):
            d = int(value)
            m = int((value - d) * 60)
            s = round(((value - d) * 60 - m) * 60, 2)
            return (R(d), R(m), R(int(round(s * 100)), 100))
        exif[photo.GPS_IFD] = {1: "N", 2: dms(gps[0]), 3: "E", 4: dms(gps[1])}
    if taken:
        exif[photo.EXIF_IFD] = {photo.DATETIME_ORIGINAL: taken}
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


SCHOOL_GPS = (float(fake_kakao.SCHOOL["y"]), float(fake_kakao.SCHOOL["x"]))


class FakeVision(RuleBrain):
    """사진을 보는 Claude 대신 정해 둔 분석을 돌려준다 (예/아니요 판단 등 나머지는 규칙 엔진)."""

    def __init__(self, **analysis):
        self.analysis = PhotoAnalysis(**(SIDEWALK | analysis))
        self.seen: list[tuple[dict, bytes | None]] = []

    def look(self, ctx, image):
        self.seen.append((ctx, image))
        return self.analysis


@pytest.fixture
def vision(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)

    def install(**analysis) -> FakeVision:
        fake = FakeVision(**analysis)
        monkeypatch.setattr(nodes, "get_brain", lambda: Brain(fake))
        return fake

    return install


def new_session() -> str:
    return client.post("/api/sessions").json()["session_id"]


def send(sid: str, text: str = "", image: bytes | None = None, lang: str = "") -> list[dict]:
    body: dict = {"text": text, "lang": lang}
    if image is not None:
        body["photo"] = {"name": "scene.jpg", "data": base64.b64encode(image).decode()}
    resp = client.post(f"/api/sessions/{sid}/messages", json=body)
    assert resp.status_code == 200, resp.text
    return [json.loads(line) for line in resp.text.splitlines() if line]


def ended(events: list[dict]) -> list[str]:
    return [e["node"] for e in events if e["type"] == "node_end"]


def node_data(events: list[dict], node: str) -> dict:
    return next(e for e in events if e["type"] == "node_end" and e["node"] == node)["data"]


# ── 사진 정보(EXIF) ──

def test_reads_gps_and_time_and_keeps_only_a_small_copy_without_metadata():
    p = photo.prepare(jpeg(SCHOOL_GPS, "2026:10:02 14:30:05", size=(4000, 3000)), "현장.jpg")
    assert (p["width"], p["height"]) == (1568, 1176)

    meta = photo.read_exif(p["id"])
    assert meta["ok"] and meta["source"] == "exif"
    assert meta["data"] == {"gps": {"lat": 35.2477, "lon": 128.5867}, "taken_at": "2026-10-02 14:30"}

    small = Image.open(io.BytesIO(photo.image(p["id"])))
    assert small.format == "JPEG" and max(small.size) == 1568
    assert len(small.getexif()) == 0  # AI에 보내는 사본에는 위치 정보가 없다


def test_photo_without_gps_says_so():
    meta = photo.read_exif(photo.prepare(jpeg())["id"])
    assert meta["data"] == {"gps": None, "taken_at": ""}
    assert "GPS" in meta["summary"]


def test_zero_gps_is_ignored():
    exif = Image.Exif()
    exif[photo.GPS_IFD] = {1: "N", 2: (R(0), R(0), R(0)), 3: "E", 4: (R(0), R(0), R(0))}
    loaded = Image.Exif()
    loaded.load(exif.tobytes())
    assert photo.gps(loaded) is None


def test_broken_exif_is_treated_as_no_gps():
    p = photo.prepare(jpeg())
    photo._store[p["id"]]["exif"] = b"Exif\x00\x00MM\x00*broken"
    meta = photo.read_exif(p["id"])
    assert meta["ok"] and meta["data"]["gps"] is None


def test_rejects_files_that_are_not_photos_or_too_big(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(photo.PhotoError, match="photo.unreadable"):
        photo.prepare(b"%PDF-1.7 not a photo")
    monkeypatch.setattr(photo, "MAX_BYTES", 10)
    with pytest.raises(photo.PhotoError, match="photo.too_big"):
        photo.prepare(jpeg())


def test_korean_time_for_drafts():
    assert photo.korean_time("2026-10-02 14:30") == "2026년 10월 2일 오후 2시 30분"
    assert photo.korean_time("2026-10-02 09:00") == "2026년 10월 2일 오전 9시"
    assert photo.korean_time("") == ""


# ── 예/아니요 판단 (규칙 대체 경로) ──

@pytest.mark.parametrize("reply, answer, issue", [
    ("예", "yes", ""),
    ("네 맞아요", "yes", ""),
    ("네, 어제부터 계속 그래요", "yes", "어제부터 계속 그래요"),
    ("Yes", "yes", ""),
    ("Có", "yes", ""),
    ("是的", "yes", ""),
    ("아니요", "no", ""),
    ("아니요, 옆에 쓰레기가 문제예요", "no", "옆에 쓰레기가 문제예요"),
    ("No", "no", ""),
    ("Không", "no", ""),
    ("不是", "no", ""),
    ("음...", "unclear", ""),
])
def test_rule_photo_answer(reply, answer, issue):
    out = RuleBrain().photo_answer({"reply": reply, "question": "", "scene": "", "language": "ko"})
    assert (out.answer, out.issue) == (answer, issue)


# ── 사진으로 시작하는 민원 흐름 ──

def test_photo_with_gps_asks_yes_no_then_finds_offices_at_the_photo_location(vision):
    fake = vision()
    sid = new_session()
    events = send(sid, image=jpeg(SCHOOL_GPS, "2026:10:02 14:30:05"))

    assert ended(events) == ["guard", "look"]
    assert [e["tool"] for e in events if e["type"] == "tool_start"] == ["photo_meta", "reverse_geocode"]
    look = node_data(events, "look")
    assert look["location"]["from_photo"] and look["location"]["sigungu"] == "창원시 마산회원구"
    assert look["photo"]["analysis"]["issue"] == SIDEWALK["issue"]
    assert fake.seen[0][1] == photo.image(look["photo"]["id"])  # 줄인 사본을 AI에 보냄

    ask = events[-1]
    assert ask["type"] == "ask" and ask["kind"] == "photo"
    assert ask["questions"][0]["text"] == SIDEWALK["question"]
    assert [o["value"] for o in ask["options"]] == ["예", "아니요"]

    events = send(sid, "예")  # 화면의 '예' 버튼
    # 위치는 사진으로 확정했으므로 위치를 묻거나 지도 검색(locate)하지 않고 바로 관할 기관을 찾는다
    assert ended(events) == ["confirm_photo", "understand", "plan", "check", "act", "decide", "draft", "review", "deliver"]
    assert node_data(events, "confirm_photo")["user_input"].startswith(SIDEWALK["issue"])
    assert "사진 촬영 위치: 경남 창원시 마산회원구 합성동로 30 부근" in node_data(events, "confirm_photo")["user_input"]
    assert "2026년 10월 2일 오후 2시 30분" in node_data(events, "confirm_photo")["user_input"]
    assert node_data(events, "understand")["understanding"]["category"] == "road_damage"
    facts = {f["slot"]: f["value"] for f in node_data(events, "check")["info"]["facts"]}
    assert facts["location"].startswith("경남 창원시 마산회원구 합성동로 30 부근")

    ready = events[-1]
    assert ready["type"] == "ready"
    assert ready["location"]["address"] == "경남 창원시 마산회원구 합성동로 30" and ready["location_confirmed"]
    assert ready["decision"]["agency"]["agency"] == "창원시 마산회원구청"
    assert "합성동로" in ready["package"]["body"]

    log = client.get(f"/api/sessions/{sid}").json()["log"]
    look_log = next(entry for entry in log if entry["node"] == "look" and entry["title"] == "사진 분석")
    assert look_log["source"] == "llm" and "사진 촬영 위치" in look_log["detail"]
    answer_log = next(entry for entry in log if entry["node"] == "confirm_photo")
    assert answer_log["source"] == "rule" and "버튼" in answer_log["detail"]


def test_photo_without_gps_continues_with_the_usual_location_questions(vision):
    vision()
    sid = new_session()
    events = send(sid, image=jpeg())
    assert [e["tool"] for e in events if e["type"] == "tool_start"] == ["photo_meta"]  # 좌표가 없으니 주소 변환 없음
    assert "GPS 정보 없음" in node_data(events, "look")["log"][0]["detail"]
    assert "location" not in node_data(events, "look")

    events = send(sid, "네")
    assert ended(events) == ["confirm_photo", "understand", "plan", "check"]
    ask = events[-1]
    assert ask["type"] == "ask" and ask["kind"] == ""
    assert "location" in {q["slot"] for q in ask["questions"]}  # 기존 방식대로 위치를 묻는다


def test_no_with_a_different_problem_uses_what_the_citizen_said(vision):
    vision()
    sid = new_session()
    send(sid, image=jpeg(SCHOOL_GPS))
    events = send(sid, "아니요, 옆에 쓰레기가 매일 쌓여 있는 게 문제예요")
    user_input = node_data(events, "confirm_photo")["user_input"]
    assert "쓰레기" in user_input and SIDEWALK["issue"] not in user_input
    assert "AI가 본 사진 속 장면" not in user_input  # 시민이 아니라고 한 짐작의 장면은 남기지 않는다
    assert node_data(events, "understand")["understanding"]["category"] == "garbage"


def test_plain_no_asks_what_the_problem_is(vision):
    vision()
    sid = new_session()
    send(sid, image=jpeg(SCHOOL_GPS))
    events = send(sid, "아니요")
    assert ended(events) == ["confirm_photo"]
    ask = events[-1]
    assert ask["kind"] == "photo" and ask["options"] == []
    assert "어떤 점이 불편하신지" in ask["questions"][0]["text"]

    events = send(sid, "가로등이 꺼져서 밤에 너무 어두워요")
    assert "AI가 본 사진 속 장면" not in node_data(events, "confirm_photo")["user_input"]
    assert node_data(events, "understand")["understanding"]["category"] == "street_light"


def test_unclear_answer_is_asked_once_more_then_used_as_is(vision):
    vision()
    sid = new_session()
    send(sid, image=jpeg(SCHOOL_GPS))
    events = send(sid, "음...")
    assert ended(events) == ["confirm_photo"]
    assert events[-1]["questions"][0]["text"].startswith("'예' 또는 '아니요'로 답해 주세요.")
    assert [o["value"] for o in events[-1]["options"]] == ["예", "아니요"]

    events = send(sid, "글쎄요")
    assert ended(events)[:2] == ["confirm_photo", "understand"]


def test_text_with_unrelated_photo_skips_the_question(vision):
    vision(relevant=False, issue="", question="", category="other", scene="음식 사진입니다.")
    sid = new_session()
    events = send(sid, "집 앞 보도블록이 깨져서 걸려 넘어질 뻔했어요", image=jpeg(SCHOOL_GPS))
    assert ended(events)[:3] == ["guard", "look", "understand"]  # 묻지 않고 시민이 쓴 말로 진행
    assert "사진에서 생활불편을 찾지 못함" in node_data(events, "look")["log"][0]["detail"]
    # 뒤 단계(문제 분석·대화)가 사진에 무엇이 있었는지 알도록 AI가 본 장면을 남긴다
    assert "AI가 본 사진 속 장면: 음식 사진입니다." in node_data(events, "look")["user_input"]


class UnclearVision(FakeVision):
    """'여기 위치 알려줘'처럼 불편을 말하지 않은 글은 불분명한 입력으로 보는 Claude 대신."""

    def understand(self, text):
        u = super().understand(text)
        if "위치 알려줘" in text and "넘어질" not in text:
            return u.model_copy(update={"intent": "unclear", "reply": "어떤 점이 불편하신가요?"})
        return u


def test_photo_is_looked_at_again_when_citizen_asks_to_find_the_problem(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    fake = UnclearVision(relevant=False, issue="", question="", category="other", scene="야구장 앞 횡단보도를 오토바이가 지나갑니다.")
    monkeypatch.setattr(nodes, "get_brain", lambda: Brain(fake))
    sid = new_session()

    events = send(sid, "여기 위치 알려줘", image=jpeg(SCHOOL_GPS))
    assert events[-1]["type"] == "redirect"  # 불편을 찾지 못해 대화로 답함
    chat_message = node_data(events, "chat")["chat_history"][0]["text"]
    assert "AI가 본 사진 속 장면: 야구장 앞 횡단보도를 오토바이가 지나갑니다." in chat_message  # 대화 단계도 사진 내용을 안다

    # "사진 보고 찾아 줘": 앞에서 올린 사진을 이어서 한 말과 함께 다시 보고, 이번에는 짐작한 불편을 묻는다
    fake.analysis = PhotoAnalysis(**SIDEWALK)
    events = send(sid, "너가 사진 보고 찾아줘")
    assert ended(events)[:2] == ["guard", "look"]
    assert len(fake.seen) == 2 and fake.seen[1][0]["text"] == "여기 위치 알려줘\n너가 사진 보고 찾아줘"  # 사진 메모는 겹치지 않음
    assert events[-1]["type"] == "ask" and events[-1]["kind"] == "photo"
    assert node_data(events, "look")["location"]["from_photo"]

    events = send(sid, "예")
    user_input = node_data(events, "confirm_photo")["user_input"]
    assert user_input.count("(현장 사진 있음") == 1 and "AI가 본 사진 속 장면" not in user_input  # '예'면 확인한 불편만
    assert events[-1]["type"] == "ready"


def test_photo_is_looked_at_again_only_once(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    fake = UnclearVision(relevant=False, issue="", question="", category="other", scene="하늘 사진입니다.")
    monkeypatch.setattr(nodes, "get_brain", lambda: Brain(fake))
    sid = new_session()
    send(sid, "여기 위치 알려줘", image=jpeg())
    send(sid, "사진 보고 위치 알려줘")
    events = send(sid, "위치 알려줘 제발")
    assert "look" not in ended(events) and len(fake.seen) == 2


def test_emergency_scene_in_photo_triggers_112_119_notice(vision):
    vision(emergency=True, issue="건물에서 불이 나고 있어요.", question="건물에 불이 난 게 맞나요?", category="other")
    events = send(new_session(), image=jpeg())
    assert node_data(events, "look")["safety"]["emergency"]


def test_rule_engine_cannot_see_photos_so_it_asks_for_a_description(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    sid = new_session()
    events = send(sid, image=jpeg())
    look_log = node_data(events, "look")["log"][0]
    assert look_log["source"] == "rule" and "분석하지 못함" in look_log["detail"]
    ask = events[-1]
    assert ask["kind"] == "photo" and ask["options"] == []
    assert ask["questions"][0]["text"].startswith("사진을 분석하지 못했어요")

    events = send(sid, "집 앞 보도블록이 깨져서 걸려 넘어질 뻔했어요")
    assert ended(events) == ["confirm_photo", "understand", "plan", "check"]
    assert node_data(events, "understand")["understanding"]["category"] == "road_damage"


def test_question_language_follows_the_screen_when_there_is_no_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    events = send(new_session(), image=jpeg(), lang="en")
    assert events[-1]["questions"][0]["text"].startswith("I couldn't analyze the photo")


def test_not_a_photo_is_rejected_in_the_screen_language():
    sid = new_session()
    resp = client.post(f"/api/sessions/{sid}/messages",
                       json={"text": "", "lang": "ko", "photo": {"name": "a.pdf", "data": base64.b64encode(b"%PDF").decode()}})
    assert resp.status_code == 400
    assert "JPG·PNG·WEBP" in resp.json()["detail"]
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": "  "}).status_code == 422


def test_photo_sent_while_answering_questions_is_ignored_with_notice(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    sid = new_session()
    send(sid, "학교 앞 횡단보도가 너무 위험해요.")
    events = send(sid, "창원시 마산회원구 합성동 합성초등학교 정문 앞이고 평일 등하교 시간에 그래요", image=jpeg())
    assert events[0]["type"] == "error" and events[0]["code"] == "photo_later"
    assert events[-1]["type"] == "ready"


# ── Claude Code에 사진 보내기 ──

def test_claude_gets_the_photo_through_stream_json(monkeypatch: pytest.MonkeyPatch, tmp_path):
    exe = tmp_path / "claude.exe"
    exe.write_text("")
    monkeypatch.setattr(brain_module, "settings", dataclasses.replace(
        brain_module.settings, claude_cli=str(exe), claude_vision_model="claude-opus-5-5", claude_effort_vision="high"))
    stream = "\n".join(json.dumps(line, ensure_ascii=False) for line in (
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": []}},
        {"type": "result", "is_error": False, "structured_output": SIDEWALK},
    ))
    fake = FakeClaude(stream)
    monkeypatch.setattr(brain_module.subprocess, "Popen", fake)

    image = photo.image(photo.prepare(jpeg())["id"])
    result = ClaudeCodeBrain().look({"text": "", "language": "ko"}, image)

    assert result == PhotoAnalysis(**SIDEWALK)
    cmd = fake.calls[0]["cmd"]
    assert cmd[cmd.index("--input-format") + 1] == "stream-json" and cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5" and cmd[cmd.index("--effort") + 1] == "high"
    assert cmd[cmd.index("--tools") + 1] == ""
    message = json.loads(fake.calls[0]["proc"].input)
    blocks = message["message"]["content"]
    assert blocks[0]["type"] == "image" and base64.b64decode(blocks[0]["source"]["data"]) == image
    assert json.loads(blocks[1]["text"])["language"] == "ko"
