"""결과물 만들기: 민원 패키지 PDF와 내려받기 API."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from minwon.api import app
from minwon.tools import export, kakao
from tests import fake_kakao

VALUES = {
    "understanding": {"category": "street_light", "category_label": "가로등·보안등 고장"},
    "decision": {
        "agency": {"agency": "합성1동 행정복지센터", "unit": "보안등 담당", "duty": "골목길 보안등 고장 접수", "phone": "055-000-0000"},
        "channel": {"id": "safety_report", "name": "안전신문고", "url": "https://www.safetyreport.go.kr", "phone": ""},
        "period": "보통 3~7일",
        "reason": "보안등 담당이 골목길 보안등 고장 접수를 맡고 있어 제출합니다.",
        "steps": ["기둥 관리번호를 확인합니다.", "야간 사진을 찍습니다.", "안전신문고에 신고합니다."],
        "cautions": ["도로변 가로등이면 구청으로 이송될 수 있습니다."],
        "others": [{"agency": "창원시 마산회원구청", "unit": "도로 관리 부서"}],
    },
    "package": {
        "title": "합성초등학교 후문 골목 보안등 수리 요청",
        "body": "안녕하십니까. 합성초등학교 후문 골목의 보안등이 [언제부터] 꺼져 있어, 밤길이 어둡습니다. 점검과 수리를 부탁드립니다.",
        "evidence": [{"item": "꺼진 상태의 야간 사진", "level": "recommended", "why": "고장 상태를 확인할 수 있어요.", "basis": ""}],
        "tips": ["접수번호를 메모해 두세요."],
        "version": 1,
    },
    "cases": {"items": [{"title": "보안등 고장 신고는 어디에 하나요", "agency": "창원시", "date": "2024-03-12",
                         "url": "https://www.epeople.go.kr/nep/pttn/gnrlPttn/pttnSmlrCaseDetail.npaid?epUnionSn=1001&dutySctnNm=tqapttn"},
                        {"title": "골목 보안등 수리 요청", "agency": "김해시", "date": "2023-11-05", "url": ""}],
              "source_name": "국민권익위원회 민원정책 질의응답 (공공데이터포털)"},
    "location_confirmed": True,
}


def _has_font() -> bool:
    try:
        export.korean_fonts()
        return True
    except export.ExportError:
        return False


needs_font = pytest.mark.skipif(not _has_font(), reason="이 PC에 한글 글꼴이 없어 PDF 생성은 건너뜀")


@needs_font
def test_package_pdf_is_created_and_reflects_edits():
    pdf, pages = export.package_pdf(VALUES)
    assert pdf.startswith(b"%PDF") and pages >= 1
    # 사례 제목을 누르면 국민신문고 원문으로 (링크가 있는 사례만)
    assert pdf.count(b"/URI (https://www.epeople.go.kr/nep/pttn/gnrlPttn/pttnSmlrCaseDetail.npaid?epUnionSn=1001") >= 1
    edited, _ = export.package_pdf(VALUES, title="고친 제목", body="고친 본문입니다. " * 80)
    assert edited.startswith(b"%PDF") and edited != pdf

    r = export.export_pdf(VALUES)
    assert r["ok"] and r["data"]["pages"] >= 1 and r["data"]["name"].startswith("AI민원길잡이_가로등·보안등_고장_")


def test_missing_font_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(export, "settings", dataclasses.replace(export.settings, pdf_font_path="Z:/없는/글꼴.ttf"))
    r = export.export_pdf(VALUES)
    assert not r["ok"] and r["source"] == "error" and "글꼴" in r["error"]


@needs_font
def test_download_endpoints_after_flow(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kakao, "request", fake_kakao.request)
    client = TestClient(app)
    sid = client.post("/api/sessions").json()["session_id"]
    assert client.get(f"/api/sessions/{sid}/files/package.pdf").status_code == 409  # 완성 전

    client.post(f"/api/sessions/{sid}/messages", json={"text": "창원 합성초등학교 앞 횡단보도가 평일 아침마다 위험해요"})
    files = client.get(f"/api/sessions/{sid}").json()["files"]
    assert files["pdf"]["pages"] >= 1 and set(files) == {"pdf"}

    pdf = client.get(f"/api/sessions/{sid}/files/package.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert "filename*=UTF-8''AI" in pdf.headers["content-disposition"]

    edited = client.post(f"/api/sessions/{sid}/files/package.pdf", json={"title": "고친 제목", "body": "고친 본문"})
    assert edited.status_code == 200 and edited.content.startswith(b"%PDF")

    assert client.get(f"/api/sessions/{sid}/files/followup.ics").status_code == 404  # 일정 파일 기능은 없앰


def test_blanks_skip_bracket_headings():
    body = "[위치]\n- 창원시 합성동 [ ] 골목\n[현재 상황]\n- 처음 본 날: [ ]월 [ ]일\n- 개수: [몇 개]"
    assert export.blanks(body) == ["[ ]", "[ ]", "[ ]", "[몇 개]"]
