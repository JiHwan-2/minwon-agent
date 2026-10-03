"""민원 서비스 안내 Tool: 받는 방법 조회, 가까운 기관·무인민원발급기 찾기, 지금 운영 여부 확인."""

from datetime import datetime, timedelta, timezone

from minwon import knowledge
from minwon.tools import kakao, kiosk, regions, tool_result

KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어 고정 시차로 충분하다
WEEKDAYS = "월화수목금토일"


def current_time() -> datetime:
    return datetime.now(KST)


def _is_workday(day: datetime) -> bool:
    return day.weekday() < 5 and day.strftime("%m-%d") not in knowledge.holidays(day.year)


def now_info(now: datetime | None = None) -> dict:
    now = now or current_time()
    holiday = now.strftime("%m-%d") in knowledge.holidays(now.year)
    weekend = now.weekday() >= 5
    # 관공서가 다음에 문을 여는 평일 (오늘이 평일이고 아직 18시 전이면 오늘)
    day = now if _is_workday(now) and now.strftime("%H:%M") < "18:00" else now + timedelta(days=1)
    while not _is_workday(day):
        day += timedelta(days=1)
    return {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"), "weekday": WEEKDAYS[now.weekday()],
            "holiday": holiday, "weekend": weekend, "workday": not (holiday or weekend),
            "next_workday": f"{day.strftime('%Y-%m-%d')}({WEEKDAYS[day.weekday()]})"}


def now_label(now: dict) -> str:
    day = "공휴일" if now["holiday"] else "주말" if now["weekend"] else "평일"
    return f"{now['date']}({now['weekday']}, {day}) {now['time']}"


def status(hours: dict | None, now: dict) -> dict:
    """지금 운영 중인지: open | closed | unknown, 오늘 운영 시간."""
    if not hours:
        return {"state": "unknown", "today": ""}
    key = "weekday" if now["workday"] else "holiday"
    if key not in hours:
        return {"state": "unknown", "today": ""}
    span = hours[key]
    if span is None:
        return {"state": "closed", "today": "휴무"}
    start, end = span
    if start == "00:00" and end in ("24:00", "23:59"):
        return {"state": "open", "today": "24시간"}
    end = "24:00" if end == "00:00" else end
    return {"state": "open" if start <= now["time"] < end else "closed", "today": f"{start}~{end}"}


def service_lookup(code: str) -> dict:
    """Tool: 지식베이스에서 이 민원 서비스를 받는 방법·수수료·준비물·찾아갈 기관을 조회한다."""
    s = knowledge.service(code)
    data = {"code": code, "label": s["label"], "group": s["group"], "summary": s["summary"], "channels": s["channels"],
            "prepare": s["prepare"], "cautions": s["cautions"], "deadline": s.get("deadline", ""), "basis": s["basis"],
            "checked": knowledge.services_checked(), "needs": s["needs"], "search_at": s["search_at"],
            "offices": s["offices"], "kiosk": s["kiosk"]}
    ways = ", ".join(f"{c['name']}({c.get('fee') or c.get('phone', '')})" for c in s["channels"])
    return tool_result("service_kb", True, "kb", f"{s['label']}: {ways}", data)


def _places(docs: list[dict], kind: str, info: dict) -> list[dict]:
    return [
        {
            "kind": kind,
            "name": d.get("place_name", ""),
            "address": d.get("road_address_name") or d.get("address_name", ""),
            "phone": d.get("phone", ""),
            "distance_m": int(d["distance"]) if d.get("distance") else None,
            "url": d.get("place_url", ""),
            "hours": info.get("hours"),
            "hours_note": info.get("hours_note", ""),
        }
        for d in docs
    ]


def _keep(name: str, info: dict) -> bool:
    if any(word in name for word in info.get("exclude", [])):
        return False
    if suffix := info.get("suffix"):
        return name.endswith(tuple(suffix))
    return any(word in name for word in info.get("match", [])) if info.get("match") else True


def find_offices(kind: str, location: dict) -> dict:
    """Tool: 위치 주변의 기관(행정복지센터·시·군·구청·경찰서 등)을 가까운 순으로 찾는다."""
    tool = f"find_offices:{kind}"
    info = knowledge.office_kind(kind)
    if not (location.get("x") and location.get("y")):
        return tool_result(tool, False, "skipped", f"위치를 몰라 {info['label']} 검색을 건너뜀", [])
    query = info["query"].replace("{office}", regions.office_name(location.get("sigungu", "")))
    near = {"x": location["x"], "y": location["y"], "radius": min(info.get("radius", 5000), 20000), "sort": "distance"}
    try:
        docs, n = kakao.keyword(query, size=10, **near)
    except kakao.KakaoError as e:
        return tool_result(tool, False, "error", f"{info['label']} 검색 실패 → 온라인·일반 안내로 대체", [], max(e.attempts - 1, 0), str(e))
    places = [p for p in _places(docs, kind, info) if _keep(p["name"], info)][:3]
    if not places:
        return tool_result(tool, False, "kakao", f"가까운 {info['label']}을(를) 찾지 못함", [], n - 1)
    top = places[0]
    distance = f", {top['distance_m']}m" if top["distance_m"] is not None else ""
    return tool_result(tool, True, "kakao", f"{top['name']}{distance} 외 {len(places) - 1}곳" if len(places) > 1 else f"{top['name']}{distance}",
                       places, n - 1)


def _is_kiosk(name: str) -> bool:
    return "무인민원" in name or "민원발급기" in name


def find_kiosks(location: dict) -> dict:
    """Tool: 가까운 무인민원발급기를 카카오로 찾고, 공공데이터(행정안전부)의 운영시간을 주소로 맞춰 붙인다."""
    info = knowledge.kiosk_info()
    if not (location.get("x") and location.get("y")):
        return tool_result("find_kiosks", False, "skipped", "위치를 몰라 무인민원발급기 검색을 건너뜀", [])
    near = {"x": location["x"], "y": location["y"], "radius": info["radius"], "sort": "distance"}
    try:
        docs, n = kakao.keyword(info["query"], size=15, **near)
    except kakao.KakaoError as e:
        return tool_result("find_kiosks", False, "error", "무인민원발급기 검색 실패 → 온라인·방문 안내로 대체", [], max(e.attempts - 1, 0), str(e))
    places = [p | {"spot": "", "hours_source": ""} for p in _places(docs, "kiosk", {"hours_note": info["hours_note"]}) if _is_kiosk(p["name"])][:3]

    error, matched = "", 0
    try:
        data = kiosk.installations(location.get("region_code", ""))
    except (kiosk.KioskDataError, Exception) as e:  # 공공데이터가 안 되면 카카오 위치만으로 안내한다
        data, error = [], str(e) if isinstance(e, kiosk.KioskDataError) else f"무인민원발급기 공공데이터 연결 실패 ({type(e).__name__})"
    by_key = {}
    for item in data:
        by_key.setdefault(item["key"], item)
    for p in places:
        item = by_key.get(kiosk.address_key(p["address"]))
        if item and item["key"]:
            p |= {"hours": item["hours"] or None, "hours_note": item["hours_note"] or p["hours_note"], "spot": item["spot"],
                  "hours_source": "data_go_kr"}
            matched += 1
    if not places and data:
        # 카카오에 없으면 같은 시·군·구 공공데이터 발급기를 거리 없이 보여 준다
        sigungu = location.get("sigungu", "")
        local = [i for i in data if sigungu and sigungu in i["address"]][:3]
        places = [{"kind": "kiosk", "name": i["name"], "address": i["address"], "phone": "", "distance_m": None, "url": "",
                   "hours": i["hours"] or None, "hours_note": i["hours_note"], "spot": i["spot"], "hours_source": "data_go_kr"} for i in local]
        matched = len(places)

    source = "kakao+data_go_kr" if matched else "kakao"
    if not places:
        return tool_result("find_kiosks", False, source, "가까운 무인민원발급기를 찾지 못함", [], n - 1, error)
    top = places[0]
    distance = f", {top['distance_m']}m" if top["distance_m"] is not None else ""
    summary = f"{len(places)}곳 (가장 가까운 곳: {top['name']}{distance})"
    summary += f" · 운영시간 {matched}곳 확인 (공공데이터)" if matched else " · 운영시간은 설치 장소마다 달라 확인 필요"
    return tool_result("find_kiosks", True, source, summary, places, n - 1, error)


def check_hours(offices: dict[str, list[dict]], kiosks: list[dict], now: dict) -> dict:
    """Tool: 지금 시각(한국 시간)·주말·공휴일 기준으로 각 기관·발급기가 운영 중인지 표시한다."""
    marked = {kind: [p | status(p.get("hours"), now) for p in places] for kind, places in offices.items()}
    marked_kiosks = [p | status(p.get("hours"), now) for p in kiosks]
    everything = [p for places in marked.values() for p in places] + marked_kiosks
    open_count = sum(p["state"] == "open" for p in everything)
    unknown = sum(p["state"] == "unknown" for p in everything)
    summary = f"{now_label(now)} 기준 운영 중 {open_count}곳 / 운영 안 함 {len(everything) - open_count - unknown}곳"
    if unknown:
        summary += f" / 확인 필요 {unknown}곳"
    return tool_result("check_hours", True, "clock", summary, {"now": now, "offices": marked, "kiosks": marked_kiosks})
