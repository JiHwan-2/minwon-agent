"""카카오 로컬 API 가짜 응답 (실제 서버를 부르지 않고 Tool 동작을 검증)."""

SCHOOL = {
    "place_name": "합성초등학교",
    "address_name": "경남 창원시 마산회원구 합성동 76-5",
    "road_address_name": "경남 창원시 마산회원구 합성동로 30",
    "x": "128.5867",
    "y": "35.2477",
    "phone": "",
}
REGIONS = [
    {"region_type": "B", "region_1depth_name": "경상남도", "region_2depth_name": "창원시 마산회원구", "region_3depth_name": "합성동"},
    {"region_type": "H", "region_1depth_name": "경상남도", "region_2depth_name": "창원시 마산회원구", "region_3depth_name": "합성1동"},
]
POLICE = [
    {"place_name": "합성지구대", "address_name": "경남 창원시 마산회원구 합성동", "distance": "592", "phone": "055-000-0001"},
    {"place_name": "마산동부경찰서", "address_name": "경남 창원시 마산회원구 양덕동", "distance": "944", "phone": "055-000-0002"},
]
CENTER = [{"place_name": "합성1동행정복지센터", "address_name": "경남 창원시 마산회원구 합성동", "distance": "300", "phone": "055-000-0003"}]


def request(path: str, params: dict, retries: int = 1):
    query = params.get("query", "")
    if path == "geo/coord2regioncode.json":
        return {"documents": REGIONS}, 1
    if path == "search/keyword.json":
        if "합성초등학교" in query:
            return {"documents": [SCHOOL]}, 1
        if query == "경찰서":
            return {"documents": POLICE}, 1
        if "행정복지센터" in query:
            return {"documents": CENTER}, 1
    return {"documents": []}, 1
