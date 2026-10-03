"""공공데이터포털 「행정안전부_무인민원발급기정보 조회서비스」: 발급기 설치 장소·평일/공휴일 운영시간.

좌표가 없는 데이터라, 카카오로 찾은 가까운 발급기와 주소(도로명+건물번호)로 맞춰 운영시간을 붙인다.
같은 시·도 데이터는 한 번 받아 6시간 동안 메모리에 둔다 (하루 1번 갱신되는 데이터).
"""

import re
import time
from urllib.parse import unquote

import httpx

from minwon.settings import settings

BASE = "https://apis.data.go.kr/1741000/kiosk_info/installation_info"
PAGE = 100
MAX_PAGES = 30
TTL = 6 * 3600
_cache: dict[str, tuple[float, list[dict]]] = {}


class KioskDataError(Exception):
    pass


def _key() -> str:
    return unquote(settings.data_go_kr_service_key)  # Encoding 키를 넣어도 풀어서 쓴다


def _hhmm(value) -> str:
    """'0900'·'09:00'·'9:00' → '09:00'. 알 수 없으면 빈 문자열."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) in (3, 4):
        digits = digits.zfill(4)
        hour, minute = int(digits[:2]), int(digits[2:])
        if 0 <= hour <= 24 and 0 <= minute < 60:
            return f"{hour:02d}:{minute:02d}"
    return ""


def _span(start, end) -> list[str] | None:
    s, e = _hhmm(start), _hhmm(end)
    return [s, e] if s and e else None


def address_key(address: str) -> str:
    """주소를 '도로명+건물번호'로 줄인다 (카카오 주소와 공공데이터 주소를 맞출 때). 없으면 빈 문자열."""
    m = re.search(r"([가-힣A-Za-z0-9.]+(?:로|길))\s*(\d+(?:-\d+)?)", address or "")
    return f"{m.group(1)}{m.group(2)}" if m else ""


def _item(raw: dict) -> dict:
    note = (raw.get("OPER_HR_REF_CN") or "").strip()
    weekday = _span(raw.get("WKDY_OPER_BGNG_TM"), raw.get("WKDY_OPER_END_TM"))
    holiday = _span(raw.get("LHLDY_OPER_BGNG_TM"), raw.get("LHLDY_OPER_END_TM"))
    hours = {}
    if weekday:
        hours["weekday"] = weekday
    if holiday:
        hours["holiday"] = holiday
    elif weekday and "휴무" in note:
        hours["holiday"] = None  # 공휴일·주말 휴무
    return {
        "name": (raw.get("ISSUMCHN_NM") or "").strip(),
        "manager": (raw.get("MNG_INST_NM") or "").strip(),
        "address": (raw.get("INSTL_PLC_ADDR") or "").strip(),
        "spot": " ".join(v for v in ((raw.get("INSTL_PLC_PSTN") or "").strip(), (raw.get("INSTL_PLC_DTL_PSTN") or "").strip()) if v),
        "hours": hours,
        "hours_note": note,
        "in_use": (raw.get("USE_YN_NM") or "사용").strip() != "미사용",
        "key": address_key(raw.get("INSTL_PLC_ADDR") or ""),
    }


def _page(params: dict) -> tuple[list[dict], int]:
    resp = httpx.get(BASE, params={"serviceKey": _key(), "returnType": "json", "numOfRows": str(PAGE), **params}, timeout=8.0)
    if resp.status_code == 403 or "SERVICE_KEY_IS_NOT_REGISTERED" in resp.text:
        raise KioskDataError("무인민원발급기정보 조회서비스 활용신청이 필요합니다 (공공데이터포털)")
    if resp.status_code != 200:
        raise KioskDataError(f"무인민원발급기 공공데이터 오류 (HTTP {resp.status_code})")
    try:
        body = resp.json()["response"]
    except (ValueError, KeyError) as e:
        raise KioskDataError("무인민원발급기 공공데이터 응답을 읽을 수 없습니다") from e
    code = str(body.get("header", {}).get("resultCode", "00"))
    if code not in ("00", "0", "INFO-000"):
        raise KioskDataError(f"무인민원발급기 공공데이터 오류: {body.get('header', {}).get('resultMsg', code)}")
    items = (body.get("body") or {}).get("items") or {}
    rows = items.get("item", []) if isinstance(items, dict) else items
    if isinstance(rows, dict):
        rows = [rows]
    return rows, int((body.get("body") or {}).get("totalCount") or 0)


def installations(region_code: str) -> list[dict]:
    """시·도 하나의 무인민원발급기 목록. region_code는 법정동 코드(앞 두 자리가 시·도)."""
    if not _key():
        raise KioskDataError("공공데이터포털 서비스키가 설정되지 않았습니다")
    sido = (region_code or "")[:2]
    if not sido:
        raise KioskDataError("위치의 시·도 코드를 몰라 운영시간을 찾지 못했습니다")
    hit = _cache.get(sido)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    # 시도코드 표기가 두 자리인지 열 자리인지 문서에 없어 둘 다 시도한다
    for value in (sido, sido + "00000000"):
        rows, total = _page({"pageNo": "1", "cond[CTPV_CD::EQ]": value})
        if total:
            for page in range(2, min(MAX_PAGES, -(-total // PAGE)) + 1):
                more, _ = _page({"pageNo": str(page), "cond[CTPV_CD::EQ]": value})
                rows += more
            items = [i for i in map(_item, rows) if i["in_use"]]
            _cache[sido] = (time.time(), items)
            return items
    _cache[sido] = (time.time(), [])
    return []
