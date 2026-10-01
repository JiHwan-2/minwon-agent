"""카카오 로컬 API 가짜 응답 (실제 서버를 부르지 않고 Tool 동작을 검증)."""

SCHOOL = {
    "place_name": "합성초등학교",
    "address_name": "경남 창원시 마산회원구 합성동 76-5",
    "road_address_name": "경남 창원시 마산회원구 합성동로 30",
    "x": "128.5867",
    "y": "35.2477",
    "phone": "",
}
# "창원 초등학교"처럼 이름 없이 검색하면 여러 학교가 나온다
CHANGWON_SCHOOLS = [
    {"place_name": "창원초등학교", "address_name": "경남 창원시 의창구 명곡동 1", "road_address_name": "경남 창원시 의창구 하남천동길 10", "x": "128.6600", "y": "35.2400"},
    SCHOOL,
    {"place_name": "상남초등학교", "address_name": "경남 창원시 성산구 상남동 2", "road_address_name": "경남 창원시 성산구 상남로 20", "x": "128.6900", "y": "35.2200"},
]
GIMHAE_SCHOOL = {"place_name": "김해초등학교", "address_name": "경남 김해시 내동 3", "road_address_name": "경남 김해시 내동로 1", "x": "128.8800", "y": "35.2400"}


def _region(gu: str, admin: str, legal: str) -> list[dict]:
    return [
        {"region_type": "B", "region_1depth_name": "경상남도", "region_2depth_name": gu, "region_3depth_name": legal},
        {"region_type": "H", "region_1depth_name": "경상남도", "region_2depth_name": gu, "region_3depth_name": admin},
    ]


REGIONS_BY_X = {
    "128.5867": _region("창원시 마산회원구", "합성1동", "합성동"),
    "128.6600": _region("창원시 의창구", "명곡동", "명곡동"),
    "128.6900": _region("창원시 성산구", "상남동", "상남동"),
    "128.8800": _region("김해시", "내외동", "내동"),
}
REGIONS = REGIONS_BY_X["128.5867"]
POLICE = [
    {"place_name": "합성지구대", "address_name": "경남 창원시 마산회원구 합성동", "distance": "592", "phone": "055-000-0001"},
    {"place_name": "마산동부경찰서", "address_name": "경남 창원시 마산회원구 양덕동", "distance": "944", "phone": "055-000-0002"},
]
CENTER = [{"place_name": "합성1동행정복지센터", "address_name": "경남 창원시 마산회원구 합성동", "distance": "300", "phone": "055-000-0003"}]


def request(path: str, params: dict, retries: int = 1):
    query = params.get("query", "")
    if path == "geo/coord2regioncode.json":
        return {"documents": REGIONS_BY_X.get(params["x"], REGIONS)}, 1
    if path == "search/keyword.json":
        if "합성초등학교" in query:
            return {"documents": [SCHOOL]}, 1
        if "상남초등학교" in query:
            return {"documents": [CHANGWON_SCHOOLS[2]]}, 1
        if "초등학교" in query:
            return {"documents": [GIMHAE_SCHOOL, *CHANGWON_SCHOOLS]}, 1
        if query == "경찰서":
            return {"documents": POLICE}, 1
        if "행정복지센터" in query:
            return {"documents": CENTER}, 1
    return {"documents": []}, 1
