"""문장에서 시·도 / 시·군·구 / 읍·면·동을 찾는다 (지도 API를 쓸 수 없을 때의 대체 경로)."""

import re

SIDO = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
}

# 경상남도 18개 시·군 (마산·진해는 창원시로 통합)
GYEONGNAM = {
    "창원": "창원시", "마산": "창원시", "진해": "창원시", "진주": "진주시", "통영": "통영시",
    "사천": "사천시", "김해": "김해시", "밀양": "밀양시", "거제": "거제시", "양산": "양산시",
    "의령": "의령군", "함안": "함안군", "창녕": "창녕군", "고성": "고성군", "남해": "남해군",
    "하동": "하동군", "산청": "산청군", "함양": "함양군", "거창": "거창군", "합천": "합천군",
}
CHANGWON_GU = ["의창구", "성산구", "마산합포구", "마산회원구", "진해구"]
NOT_PLACE = {"하수구", "배수구", "출입구", "비상구", "환기구", "통풍구", "놀이기구", "운동기구"}

SIGUNGU = re.compile(r"(?:^|\s)([가-힣]{2,4}(?:시|군))(?:\s+([가-힣]{2,5}구))?(?=\s|$|[,.에의])")
GU_ONLY = re.compile(r"(?:^|\s)([가-힣]{2,5}구)(?=\s|$|[,.에의])")
DONG = re.compile(r"(?:^|\s)([가-힣]{1,6}\d?(?:동|읍|면))(?=\s|$|[,.에의])")


def parse(text: str) -> dict:
    result = {"sido": "", "sigungu": "", "dong": ""}
    for short, full in SIDO.items():
        if short in text:
            result["sido"] = full
            break

    city = next((full for short, full in GYEONGNAM.items() if short in text), "")
    if city:
        result["sido"] = result["sido"] or "경상남도"
        gu = next((g for g in CHANGWON_GU if g in text), "") if city == "창원시" else ""
        result["sigungu"] = f"{city} {gu}".strip()
    elif m := SIGUNGU.search(text):
        result["sigungu"] = " ".join(g for g in m.groups() if g)
    elif (m := GU_ONLY.search(text)) and m.group(1) not in NOT_PLACE:
        result["sigungu"] = m.group(1)

    if m := DONG.search(text):
        result["dong"] = m.group(1)
    return result


def office_name(sigungu: str) -> str:
    """'창원시 마산회원구' → '창원시 마산회원구청', '함안군' → '함안군청'"""
    return f"{sigungu}청" if sigungu else "관할 시·군·구청"


def city_name(sigungu: str) -> str:
    """구가 있는 시는 시 단위로: '창원시 마산회원구' → '창원시'"""
    return sigungu.split()[0] if sigungu else ""
