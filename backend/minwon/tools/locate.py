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
        loc["region_code"] = legal.get("code", "")  # 법정동 코드 (앞 두 자리가 시·도, 무인민원발급기 공공데이터 조회에 씀)
    return loc, n - 1


# 장소를 설명하는 말일 뿐 장소 이름이 아닌 단어. 지도 검색어에 섞이면 카카오가 0건을 주거나 엉뚱한 곳을 준다
# (예: '창신대학교 정문 버스정류장' → 0건, '창신대 버스정류장' → 노무법인, '창신대학교 앞' → 사진관)
NOT_NAME = {"앞", "뒤", "옆", "근처", "부근", "맞은편", "건너편", "인근", "주변", "쪽", "방향", "기준", "가장", "가까운", "사이",
            "버스정류장", "정류장", "정류소", "횡단보도", "건널목", "신호등", "가로등", "보안등", "골목", "골목길", "인도", "도로", "길가"}


def _keys(query: str) -> list[str]:
    """검색 결과가 이 장소가 맞는지 볼 장소 이름 단어들: 시·군·구·동 이름, 설명하는 말, 조사를 뺀 단어."""
    region = regions.parse(query)
    skip = {w for part in (region["sido"], region["sigungu"], region["dong"]) for w in part.split()}
    skip |= {"경남", "경상남도", *regions.SIDO, *regions.GYEONGNAM}  # '창원 초등학교'의 '창원'처럼 시 이름만 쓴 말
    keys = []
    for raw in query.split():
        word = regions._strip_token(raw)
        if (len(word) < 2 or {raw, word} & (skip | NOT_NAME | regions.GENERIC_PREFIX)
                or (regions.DONG_TOKEN.match(word) and word not in regions.NOT_DONG)):
            continue
        keys.append(word)
    return keys


def _relevant(docs: list[dict], query: str) -> list[dict]:
    """장소 이름에 시민이 말한 장소 이름(앞 세 글자)이 들어 있는 결과만 (주소·설명에만 걸린 엉뚱한 가게는 뺀다)."""
    keys = _keys(query)
    if not keys or regions.ROAD_ADDRESS.search(query) or regions.LOT_ADDRESS.search(query):
        return docs  # 주소로 찾을 때는 장소 이름을 비교하지 않는다
    names = [k for k in keys if k not in regions.LANDMARK_SUFFIXES]  # '놀이터'·'사거리' 같은 시설 종류는 이름이 아님
    if not names:
        return docs  # '초등학교'처럼 이름 없이 종류만 말했으면 후보를 그대로 보여 주고 고르게 한다

    def score(doc: dict) -> int:
        name = (doc.get("place_name") or "").replace(" ", "")
        if any(name == k or name.startswith(k) for k in names):
            return 3  # '용지호수' → '용지호수'가 '스타벅스 창원용지호수점'보다 앞
        if any(k in name for k in names):
            return 2
        return 1 if any(k[:3] in name for k in names) else 0

    return sorted((d for d in docs if score(d)), key=score, reverse=True)


def _variants(query: str) -> list[str]:
    """못 찾았을 때 다시 찾을 검색어: 시·도·시·군·구 빼기 → 설명하는 말 빼기 → 뒤에서부터 한 단어씩 줄이기 (장소 이름은 남김)."""
    region = regions.parse(query)
    drop = {w for part in (region["sido"], region["sigungu"]) for w in part.split()} | {"경남", "경상남도"}
    tokens = [t for t in query.split() if t not in drop]
    names = [t for t in tokens if t not in NOT_NAME and t not in regions.GENERIC_PREFIX]
    keys = _keys(query)
    out = [" ".join(tokens)]
    # 뒤에서부터 줄이되 장소 이름 단어가 하나도 남지 않으면 그만 (그때는 동 단위 확인으로 넘어감)
    out += [" ".join(names[:i]) for i in range(len(names), 0, -1) if any(regions._strip_token(t) in keys for t in names[:i])]
    found: list[str] = []
    for v in out:
        if v and v != query and v not in found:
            found.append(v)
    return found


def _search(query: str, context_text: str, address: bool = True) -> tuple[list[dict], int]:
    """카카오 검색 후보 최대 5개. 사용자가 말한 시·군 안의 결과를 우선한다. (후보, 재시도 횟수)"""
    docs, n = kakao.keyword(query, size=5)
    retries = n - 1
    docs = _relevant(docs, query)
    if not docs and address:
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
            used = query
            for variant in [] if candidates else _variants(query):  # 못 찾으면 검색어를 줄여 다시 찾는다
                candidates, more = _search(variant, f"{query} {context_text}", address=False)
                retries += more
                if candidates:
                    used = variant
                    break
            if candidates:
                loc, more = _with_region(candidates[0], query)
                retries += more
                ambiguous = _is_ambiguous(query, candidates)
                loc |= {"ambiguous": ambiguous, "candidates": candidates}
                where = " ".join(v for v in (loc["sigungu"], loc["dong"]) if v)
                summary = f"{loc['address']} ({where})"
                if used != query:
                    loc["approximate"] = True
                    summary = f"'{query}'(으)로는 못 찾아 '{used}'(으)로 찾음: {candidates[0]['name'] or loc['address']} · {summary}"
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


def from_coords(lat: float, lon: float) -> dict:
    """Tool: 사진 촬영 위치(GPS 좌표) → 주소·행정구역. 찾은 위치는 지도 검색 없이 바로 확정한다."""
    x, y = str(lon), str(lat)
    query = "사진 촬영 위치"
    try:
        docs, n = kakao.coord_address(x, y)
        retries = n - 1
        doc = docs[0] if docs else {}
        road = (doc.get("road_address") or {}).get("address_name", "")
        lot = (doc.get("address") or {}).get("address_name", "")
        if not (road or lot):
            return tool_result("reverse_geocode", False, "kakao", "이 좌표의 국내 주소를 찾지 못함 → 대화로 위치 확인", None, retries)
        loc, more = _with_region({"name": "", "address": road or lot, "lot_address": lot, "x": x, "y": y}, query)
    except kakao.KakaoError as e:
        return tool_result("reverse_geocode", False, "error", "사진 위치를 주소로 바꾸지 못함 → 대화로 위치 확인", None,
                           max(e.attempts - 1, 0), str(e))
    loc |= {"ambiguous": False, "candidates": [], "from_photo": True}
    if lot and lot != loc["address"]:
        loc["lot_address"] = lot
    where = " ".join(v for v in (loc["sigungu"], loc["dong"]) if v)
    return tool_result("reverse_geocode", True, "kakao", f"사진 촬영 위치: {loc['address']} 부근 ({where})", loc, retries + more)


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
