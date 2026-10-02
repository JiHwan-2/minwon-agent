"""위치 확인(geocode)과 주변 공공기관 검색(find_nearby)."""

from minwon.tools import kakao, regions, tool_result

NEARBY_LABEL = {"police": "관할 경찰서", "community_center": "행정복지센터"}


def _empty_location(query: str) -> dict:
    return {"query": query, "place_name": "", "address": "", "x": "", "y": "",
            "sido": "", "sigungu": "", "dong": "", "legal_dong": "", "ambiguous": False, "candidates": []}


def _candidate(doc: dict) -> dict:
    road = doc.get("road_address") or {}
    return {
        "name": doc.get("place_name") or "",
        "address": doc.get("road_address_name") or road.get("address_name") or doc.get("address_name", ""),
        "lot_address": doc.get("address_name", ""),
        "x": doc["x"],
        "y": doc["y"],
    }


def _with_region(candidate: dict, query: str) -> tuple[dict, int]:
    """후보 하나를 좌표→행정구역으로 확정한다. (위치, 재시도 횟수)"""
    loc = _empty_location(query) | {k: candidate[k] for k in ("x", "y", "address")} | {"place_name": candidate["name"]}
    regs, n = kakao.region(candidate["x"], candidate["y"])
    admin = next((r for r in regs if r.get("region_type") == "H"), None)
    legal = next((r for r in regs if r.get("region_type") == "B"), None)
    if admin:
        loc |= {"sido": admin["region_1depth_name"], "sigungu": admin["region_2depth_name"], "dong": admin["region_3depth_name"]}
    if legal:
        loc["legal_dong"] = legal["region_3depth_name"]
    return loc, n - 1


def _search(query: str, context_text: str) -> tuple[list[dict], int]:
    """카카오 검색 후보 최대 5개. 사용자가 말한 시·군 안의 결과를 우선한다. (후보, 재시도 횟수)"""
    docs, n = kakao.keyword(query, size=5)
    retries = n - 1
    if not docs:
        docs, n = kakao.address(query)
        retries += n - 1
    candidates = [_candidate(d) for d in docs]
    city = regions.city_name(regions.parse(f"{query} {context_text}")["sigungu"])
    in_city = [c for c in candidates if city and city in f"{c['address']} {c['lot_address']}"]
    return (in_city or candidates), retries


def _is_ambiguous(query: str, candidates: list[dict]) -> bool:
    if len(candidates) < 2:
        return False
    if not regions.is_specific_place(query):
        return True
    same_name = [c for c in candidates if c["name"] and c["name"] == candidates[0]["name"]]
    return len(same_name) > 1


def resolve_candidate(candidate: dict, query: str) -> dict:
    """사용자가 고른 후보를 행정구역까지 확정한다."""
    try:
        loc, retries = _with_region(candidate, query)
    except kakao.KakaoError as e:
        loc = _empty_location(query) | {k: candidate[k] for k in ("x", "y", "address")} | {"place_name": candidate["name"]}
        loc |= regions.parse(candidate["lot_address"] or candidate["address"])
        return tool_result("geocode", True, "text_fallback", f"선택한 위치: {loc['address']}", loc, max(e.attempts - 1, 0), str(e))
    where = " ".join(v for v in (loc["sigungu"], loc["dong"]) if v)
    return tool_result("geocode", True, "kakao", f"선택한 위치: {loc['address']} ({where})", loc, retries)


def _area_search(query: str, context_text: str) -> tuple[dict, int] | None:
    """문장에서 뽑은 '시·구 동'을 카카오 주소 검색으로 다시 찾는다 (장소 이름이 지도에 없을 때)."""
    region = regions.parse(f"{query} {context_text}")
    if not (region["sigungu"] and region["dong"]):
        return None
    docs, n = kakao.address(f"{region['sigungu']} {region['dong']}")
    if not docs:
        return None
    loc, more = _with_region(_candidate(docs[0]), query)
    return loc | {"ambiguous": False, "candidates": []}, n - 1 + more


def geocode(query: str, context_text: str = "") -> dict:
    """장소 표현 → 주소·좌표·행정구역. 후보가 여러 곳이면 ambiguous로 표시해 사용자 확인을 받게 한다.
    카카오 실패 시 문장에서 지역명을 추출하는 대체 경로."""
    retries, reason = 0, ""
    if query.strip():
        try:
            candidates, retries = _search(query, context_text)
            if candidates:
                loc, more = _with_region(candidates[0], query)
                retries += more
                ambiguous = _is_ambiguous(query, candidates)
                loc |= {"ambiguous": ambiguous, "candidates": candidates}
                where = " ".join(v for v in (loc["sigungu"], loc["dong"]) if v)
                summary = f"{loc['address']} ({where})"
                if ambiguous:
                    summary = f"후보 {len(candidates)}곳 — 사용자 확인 필요 (1순위: {candidates[0]['name'] or loc['address']})"
                return tool_result("geocode", True, "kakao", summary, loc, retries)
            reason = "카카오 검색 결과 없음"
            area = _area_search(query, context_text)
            if area:
                loc, more = area
                where = " ".join(v for v in (loc["sigungu"], loc["dong"]) if v)
                return tool_result("geocode", True, "kakao", f"장소를 못 찾아 동 단위로 확인: {where}", loc | {"approximate": True},
                                   retries + more, reason)
        except kakao.KakaoError as e:
            retries, reason = max(e.attempts - 1, 0), str(e)
    else:
        reason = "위치 검색어 없음"

    region = regions.parse(f"{query} {context_text}")
    loc = _empty_location(query) | region | {"address": " ".join(v for v in region.values() if v)}
    if region["sigungu"]:
        return tool_result("geocode", True, "text_fallback", f"문장에서 지역 추출: {loc['address']}", loc, retries, reason)
    return tool_result("geocode", False, "text_fallback", "위치를 특정하지 못함", loc, retries, reason)


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


def _is_office(name: str) -> bool:
    """행정복지센터 본청만 (같은 이름이 붙은 무인민원발급기·창구는 제외)."""
    return name.endswith(("행정복지센터", "주민센터")) and "무인" not in name


def find_nearby(kind: str, location: dict) -> dict:
    """좌표 주변에서 관할 기관을 찾는다. police=경찰서(지구대·파출소 제외), community_center=행정동 행정복지센터."""
    tool = f"find_nearby:{kind}"
    label = NEARBY_LABEL.get(kind, kind)
    if not (location.get("x") and location.get("y")):
        return tool_result(tool, False, "skipped", f"좌표가 없어 {label} 검색을 건너뜀", [])

    near = {"x": location["x"], "y": location["y"], "sort": "distance"}
    try:
        if kind == "police":
            docs, n = kakao.keyword("경찰서", size=10, radius=10000, **near)
            retries = n - 1
            places = [p for p in _places(docs) if p["name"].endswith("경찰서")]
        else:
            dong = location.get("dong", "")
            docs, n = kakao.keyword(f"{location.get('sigungu', '')} {dong} 행정복지센터".strip(), size=5, **near)
            retries = n - 1
            places = [p for p in _places(docs) if dong and dong in p["name"] and _is_office(p["name"])]
            if not places:
                docs, n = kakao.keyword("행정복지센터", size=5, radius=3000, **near)
                retries += n - 1
                places = [p for p in _places(docs) if _is_office(p["name"])]
    except kakao.KakaoError as e:
        return tool_result(tool, False, "error", f"{label} 검색 실패 → 일반 안내로 대체", [], max(e.attempts - 1, 0), str(e))

    if not places:
        return tool_result(tool, False, "kakao", f"주변에서 {label}을 찾지 못함", [], retries)
    top = places[0]
    distance = f", {top['distance_m']}m" if top["distance_m"] is not None else ""
    return tool_result(tool, True, "kakao", f"{top['name']}{distance}", places[:3], retries)
