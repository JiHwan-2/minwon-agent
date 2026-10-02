"""결과물 만들기: 민원 패키지를 PDF로, 처리 결과 확인 일정을 캘린더 파일(.ics, RFC 5545)로 만든다."""

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fpdf import FPDF

from minwon import knowledge
from minwon.settings import settings
from minwon.tools import tool_result

log = logging.getLogger(__name__)
logging.getLogger("fontTools").setLevel(logging.ERROR)  # 글꼴 부분 추출(subset) 로그가 PDF마다 수백 줄 찍히는 것을 막음

WEEKDAYS = "월화수목금토일"
EVIDENCE_GROUPS = [("required", "필수 (공식 요건)"), ("recommended", "권장 (있으면 처리에 도움)"), ("separate", "별도 절차 (피해 보상 등)")]
FOOTER = "안내 정보는 참고용이며 부서 이름은 지자체마다 다를 수 있습니다. 내용을 확인한 뒤 민원은 직접 제출해 주세요."

TEXT, MUTED, PRIMARY, WARN, FILL = (24, 34, 49), (95, 107, 124), (29, 91, 214), (154, 90, 0), (238, 241, 246)


class ExportError(RuntimeError):
    pass


def _font_candidates() -> list[tuple[Path, Path | None]]:
    win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return [
        (win / "malgun.ttf", win / "malgunbd.ttf"),
        (Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"), None),
        (Path("/Library/Fonts/NanumGothic.ttf"), Path("/Library/Fonts/NanumGothicBold.ttf")),
        (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")),
    ]


def korean_fonts() -> tuple[Path, Path]:
    """(보통, 굵게) 한글 글꼴 경로. .env 설정이 우선이고, 없으면 운영체제 기본 글꼴을 찾는다 (글꼴 파일은 저장소에 넣지 않음)."""
    if settings.pdf_font_path:
        regular = Path(settings.pdf_font_path)
        if not regular.exists():
            raise ExportError(f"PDF_FONT_PATH의 글꼴 파일이 없습니다: {regular}")
        bold = Path(settings.pdf_font_bold_path) if settings.pdf_font_bold_path else regular
        return regular, bold if bold.exists() else regular
    for regular, bold in _font_candidates():
        if regular.exists():
            return regular, bold if bold and bold.exists() else regular
    raise ExportError("한글 글꼴을 찾을 수 없습니다. .env의 PDF_FONT_PATH에 한글 TTF 글꼴 경로를 넣어 주세요")


class _Doc(FPDF):
    def __init__(self, regular: Path, bold: Path):
        super().__init__(format="A4")
        self.add_font("ko", "", str(regular))
        self.add_font("ko", "B", str(bold))
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(True, margin=20)
        self.set_lang("ko")

    def footer(self):
        self.set_y(-15)
        self.set_font("ko", "", 7.5)
        self.set_text_color(*MUTED)
        self.multi_cell(0, 4, f"{FOOTER}\n{self.page_no()} / {{nb}}", align="C")

    def write_line(self, text: str, size: float = 10, color=TEXT, style: str = "", h: float = 6, **kw):
        self.set_font("ko", style, size)
        self.set_text_color(*color)
        self.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT", align="L", **kw)  # 양쪽 정렬은 한글 띄어쓰기를 벌려 놓음

    def heading(self, text: str):
        self.ln(3)
        self.write_line(text, 12.5, PRIMARY, "B", 8)
        self.set_draw_color(*PRIMARY)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def field(self, label: str, value: str):
        self.set_font("ko", "B", 9.5)
        self.set_text_color(*MUTED)
        self.cell(26, 6, label)
        self.set_font("ko", "", 10)
        self.set_text_color(*TEXT)
        self.multi_cell(0, 6, value, new_x="LMARGIN", new_y="NEXT", align="L")


HEADING = re.compile(r"^\s*\[[^\]]+\]\s*$")
BLANK = re.compile(r"\[[^\]]+\]")


def blanks(body: str) -> list[str]:
    """시민이 채울 [ ] 빈칸 목록. 한 줄 전체가 '[위치]'처럼 대괄호뿐인 줄은 소제목으로 보고 뺀다."""
    return [m for line in body.splitlines() if not HEADING.match(line) for m in BLANK.findall(line)]


def _safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")


def pdf_filename(values: dict) -> str:
    label = values.get("understanding", {}).get("category_label", "민원")
    return f"AI민원길잡이_{_safe_name(label)}_{date.today():%Y%m%d}.pdf"


def package_pdf(values: dict, title: str | None = None, body: str | None = None) -> tuple[bytes, int]:
    """(PDF 내용, 쪽수). title·body를 주면 사용자가 화면에서 고친 초안으로 만든다."""
    regular, bold = korean_fonts()
    pkg, decision = values["package"], values["decision"]
    agency, channel = decision["agency"], decision["channel"]
    title = title or pkg["title"]
    body = body or pkg["body"]

    doc = _Doc(regular, bold)
    doc.set_title(title)
    doc.set_author("AI민원길잡이")
    doc.set_subject("민원 제출 준비서")
    doc.add_page()

    doc.write_line("민원 제출 준비서", 19, TEXT, "B", 11)
    doc.write_line(f"AI민원길잡이가 정리한 제출용 자료 · 작성일 {date.today():%Y-%m-%d} · {pkg.get('version', 1)}번째 초안", 9, MUTED)
    if values.get("location_confirmed") is False:
        doc.ln(1)
        doc.write_line("※ 위치 후보가 여러 곳이어서 1순위 후보로 안내했습니다. 제출 전에 위치와 담당 기관을 꼭 확인해 주세요.", 9.5, WARN)

    doc.heading("1. 제출할 곳")
    doc.field("담당 기관", f"{agency['agency']} {agency['unit']}")
    doc.field("담당 업무", agency["duty"])
    if agency.get("phone"):
        doc.field("전화", agency["phone"])
    where = channel["name"] + (f" ({channel['url']})" if channel.get("url") else "") + (f" · 전화 {channel['phone']}" if channel.get("phone") else "")
    doc.field("제출 창구", where)
    doc.field("처리 기간", decision["period"])
    if followup := values.get("files", {}).get("ics"):
        doc.field("처리 확인일", f"{followup['date']} ({followup['weekday']}) — 이날 접수번호로 처리 결과를 확인하세요")
    doc.field("판단 근거", decision["reason"])
    if decision.get("others"):
        doc.field("관련 기관", ", ".join(f"{o['agency']}({o['unit']})" for o in decision["others"]))

    doc.heading("2. 민원 초안")
    doc.field("제목", title)
    doc.ln(1)
    doc.set_fill_color(*FILL)
    doc.write_line(body, 10.5, TEXT, h=6.4, fill=True, padding=3)
    if count := len(blanks(body)):
        doc.write_line(f"※ [ ] 표시된 빈칸 {count}곳은 제출 전에 채워 주세요.", 9.5, WARN)

    doc.heading("3. 이렇게 진행하세요")
    for i, step in enumerate(decision["steps"], 1):
        doc.write_line(f"{i}. {step}", 10)
    for caution in decision.get("cautions", []):
        doc.write_line(f"※ {caution}", 9.5, WARN)

    doc.heading("4. 증빙자료 체크리스트")
    for level, label in EVIDENCE_GROUPS:
        items = [e for e in pkg["evidence"] if e["level"] == level]
        if not items:
            continue
        doc.write_line(label, 10, MUTED, "B")
        for e in items:
            doc.write_line(f"□ {e['item']} — {e['why']}" + (f" (근거: {e['basis']})" if e.get("basis") else ""), 10)
    for tip in pkg.get("tips", []):
        doc.write_line(f"· {tip}", 9.5, MUTED)

    cases = (values.get("cases") or {}).get("items", [])
    if cases:
        doc.heading("5. 비슷한 민원 사례")
        for c in cases:
            meta = " · ".join(x for x in (c.get("agency"), c.get("date")) if x)
            doc.write_line(f"· {c['title']}" + (f" ({meta})" if meta else ""), 10)
        doc.write_line(f"출처: {values['cases']['source_name']} — 참고용이며 처리 결과는 기관·지역마다 다를 수 있습니다.", 8.5, MUTED)

    return bytes(doc.output()), doc.page_no()


def followup_date(category: str, today: date) -> tuple[date, int, bool]:
    """(확인일, 기준 일수, 주말이라 미뤘는지). 지식베이스의 처리 기간 끝 무렵, 주말이면 다음 월요일."""
    days = knowledge.agency_rules(category).get("followup_days", 14)
    due = today + timedelta(days=days)
    shift = {5: 2, 6: 1}.get(due.weekday(), 0)
    return due + timedelta(days=shift), days, bool(shift)


def plan_followup(values: dict, today: date | None = None) -> dict:
    due, days, shifted = followup_date(values["understanding"]["category"], today or date.today())
    agency = values["decision"]["agency"]
    previous = (values.get("files") or {}).get("ics") or {}
    return {
        "name": f"민원처리확인_{due:%Y%m%d}.ics",
        "date": due.isoformat(),
        "weekday": WEEKDAYS[due.weekday()],
        "days": days,
        "shifted": shifted,
        "period": values["decision"]["period"],
        "summary": f"민원 처리 결과 확인 · {agency['agency']}",
        "uid": previous.get("uid") or f"{uuid4().hex}@minwon-agent",  # 수정 후 다시 받아도 같은 일정으로 인식되도록 유지
    }


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """RFC 5545: 한 줄은 75바이트 이하, 이어지는 줄은 공백으로 시작. 한글이 중간에서 잘리지 않게 글자 단위로 나눈다."""
    out, current = [], ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 75:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return out


def followup_ics(values: dict) -> str:
    f = values["files"]["ics"]
    decision, pkg = values["decision"], values["package"]
    agency, channel = decision["agency"], decision["channel"]
    due = date.fromisoformat(f["date"])
    where = channel["name"] + (f" {channel['url']}" if channel.get("url") else "")
    contact = f"{channel['name']}(전화 {channel['phone']})" if channel.get("phone") else "제출한 창구"
    description = "\n".join([
        f"민원: {pkg['title']}",
        f"제출처: {agency['agency']} {agency['unit']}",
        f"제출 창구: {where}",
        f"처리 기간: {f['period']}",
        "",
        "할 일",
        "1. 제출한 사이트에서 접수번호로 처리 상황을 확인합니다.",
        f"2. 답변이 없거나 처리되지 않았으면 {contact}에 문의합니다.",
        "",
        "※ 처리 기간은 기관·상황에 따라 다를 수 있습니다. (AI민원길잡이)",
    ])
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AI민원길잡이//minwon-agent//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{f['uid']}",
        f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        f"DTSTART;VALUE=DATE:{due:%Y%m%d}",
        f"DTEND;VALUE=DATE:{due + timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{_ics_text(f['summary'])}",
        f"DESCRIPTION:{_ics_text(description)}",
        *([f"URL:{channel['url']}"] if channel.get("url") else []),
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_text(f['summary'])}",
        "TRIGGER:PT9H",  # 확인일 오전 9시 알림
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def schedule_followup(values: dict, today: date | None = None) -> dict:
    """Tool: 처리 기간을 근거로 결과 확인일을 정하고 캘린더 파일을 만든다."""
    data = plan_followup(values, today)
    text = followup_ics(values | {"files": {"ics": data}})
    due = date.fromisoformat(data["date"])
    summary = f"{due.month}월 {due.day}일({data['weekday']}) 처리 결과 확인 일정 · 처리 기간 '{data['period']}' 기준 {data['days']}일 뒤"
    if data["shifted"]:
        summary += " (주말이라 월요일로)"
    return tool_result("schedule_followup", True, "generated", summary, data | {"size": len(text.encode("utf-8"))})


def export_pdf(values: dict) -> dict:
    """Tool: 민원 패키지 PDF를 만들고 열 수 있는 파일인지 확인한다."""
    try:
        content, pages = package_pdf(values)
    except ExportError as e:
        return tool_result("export_pdf", False, "error", "PDF를 만들지 못함 → 화면의 복사 기능을 이용", {"name": ""}, error=str(e))
    except Exception as e:  # 글꼴·문자 문제로 실패해도 민원 패키지는 그대로 전달
        log.exception("PDF 생성 실패")
        return tool_result("export_pdf", False, "error", "PDF를 만들지 못함 → 화면의 복사 기능을 이용", {"name": ""},
                           error=f"{type(e).__name__}: {e}"[:200])
    if not content.startswith(b"%PDF"):
        return tool_result("export_pdf", False, "error", "PDF 확인 실패", {"name": ""}, error="PDF 형식이 아닙니다")
    name = pdf_filename(values)
    return tool_result("export_pdf", True, "generated", f"민원 패키지 PDF {pages}쪽 · {len(content) / 1024:.0f}KB",
                       {"name": name, "pages": pages, "size": len(content)})
