"""위치 확인(geocode)과 주변 공공기관 검색(find_nearby)."""

from minwon.tools import kakao, regions, tool_result

NEARBY_LABEL = {"police": "관할 경찰서", "community_center": "행정복지센터"}


def _empty_location(query: str) -> dict:
    return {"query": query, "place_name": "", "address": "", "x": "", "y": "",
            "sido": "", "sigungu": "", "dong": "", "legal_dong": ""}


def _from_kakao(query: str) -> tuple[dict | None, int]:
    attempts = 0
    docs, n = kakao.keyword(query)
    attempts += n
    if not docs:
        docs, n = kakao.address(query)
        attempts += n
    if not docs:
        return None, attempts

    doc = docs[0]
    road = doc.get("road_address") or {}
    loc = _empty_location(query) | {
        "place_name": doc.get("place_name", ""),
        "address": doc.get("road_address_name") or road.get("address_name") or doc.get("address_name", ""),
        "x": doc["x"],
        "y": doc["y"],
    }
    regs, n = kakao.region(doc["x"], doc["y"])
    attempts += n
    admin = next((r for r in regs if r.get("region_type") == "H"), None)
    legal = next((r for r in regs if r.get("region_type") == "B"), None)
    if admin:
        loc |= {"sido": admin["region_1depth_name"], "sigungu": admin["region_2depth_name"], "dong": admin["region_3depth_name"]}
    if legal:
        loc["legal_dong"] = legal["region_3depth_name"]
    return loc, attempts


def geocode(query: str, context_text: str = "") -> dict:
    """장소 표현 → 주소·좌표·행정구역. 카카오 실패 시 문장에서 지역명을 추출하는 대체 경로."""
    attempts, reason = 0, ""
    if query.strip():
        try:
            loc, attempts = _from_kakao(query)
            if loc:
                where = " ".join(v for v in (loc["sigungu"], loc["dong"]) if v)
                return tool_result("geocode", True, "kakao", f"{loc['address']} ({where})", loc, attempts)
            reason = "카카오 검색 결과 없음"
        except kakao.KakaoError as e:
            attempts, reason = e.attempts, str(e)
    else:
        reason = "위치 검색어 없음"

    region = regions.parse(f"{query} {context_text}")
    loc = _empty_location(query) | region | {"address": " ".join(v for v in region.values() if v)}
    if region["sigungu"]:
        return tool_result("geocode", True, "text_fallback", f"문장에서 지역 추출: {loc['address']}", loc, attempts, reason)
    return tool_result("geocode", False, "text_fallback", "위치를 특정하지 못함", loc, attempts, reason)


def _places(docs: list[dict]) -> list[dict]:
    return [
        {
            "name": d.get("place_name", ""),
            "address": d.get("road_address_name") or d.get("address_name", ""),
            "phone": d.get("phone", ""),
            "distance_m": int(d["distance"]) if d.get("distance") else None,
            "url": d.get("place_url", ""),
        }
        for d in docs
    ]


def find_nearby(kind: str, location: dict) -> dict:
    """좌표 주변에서 관할 기관을 찾는다. police=경찰서(지구대·파출소 제외), community_center=행정동 행정복지센터."""
    tool = f"find_nearby:{kind}"
    label = NEARBY_LABEL.get(kind, kind)
    if not (location.get("x") and location.get("y")):
        return tool_result(tool, False, "skipped", f"좌표가 없어 {label} 검색을 건너뜀", [])

    near = {"x": location["x"], "y": location["y"], "sort": "distance"}
    try:
        if kind == "police":
            docs, attempts = kakao.keyword("경찰서", size=10, radius=10000, **near)
            places = [p for p in _places(docs) if p["name"].endswith("경찰서")]
        else:
            dong = location.get("dong", "")
            docs, attempts = kakao.keyword(f"{location.get('sigungu', '')} {dong} 행정복지센터".strip(), size=3, **near)
            places = [p for p in _places(docs) if dong and dong in p["name"]]
            if not places:
                docs, n = kakao.keyword("행정복지센터", size=3, radius=3000, **near)
                attempts += n
                places = _places(docs)
    except kakao.KakaoError as e:
        return tool_result(tool, False, "error", f"{label} 검색 실패 → 일반 안내로 대체", [], e.attempts, str(e))

    if not places:
        return tool_result(tool, False, "kakao", f"주변에서 {label}을 찾지 못함", [], attempts)
    top = places[0]
    distance = f", {top['distance_m']}m" if top["distance_m"] is not None else ""
    return tool_result(tool, True, "kakao", f"{top['name']}{distance}", places[:3], attempts)
