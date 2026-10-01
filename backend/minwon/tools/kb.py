"""담당 부서·제출 창구·절차 조회: 지식베이스 규칙을 실제 지역·검색 결과로 구체화한다."""

from minwon import knowledge
from minwon.tools import regions, tool_result


def _resolve(dept: dict, location: dict, nearby: dict[str, list[dict]]) -> dict:
    level = dept["level"]
    sigungu, dong = location.get("sigungu", ""), location.get("dong", "")
    phone, source = "", "kb"

    if level == "sigungu":
        agency = regions.office_name(sigungu)
        source = "kb+region" if sigungu else "kb"
    elif level == "city":
        city = regions.city_name(sigungu)
        agency = f"{city}청" if city else "관할 시·군청"
        source = "kb+region" if city else "kb"
    elif level == "dong":
        found = nearby.get("community_center") or []
        if found:
            agency, phone, source = found[0]["name"], found[0]["phone"], "kakao"
        else:
            agency = f"{dong} 행정복지센터" if dong else "관할 행정복지센터"
            source = "kb+region" if dong else "kb"
    elif level == "police":
        found = nearby.get("police") or []
        if found:
            agency, phone, source = found[0]["name"], found[0]["phone"], "kakao"
        else:
            agency = "관할 경찰서"
    else:
        agency = dept["agency"]

    return {"agency": agency, "unit": dept["unit"], "duty": dept["duty"], "phone": phone, "source": source}


def kb_lookup(category: str, location: dict, nearby: dict[str, list[dict]]) -> dict:
    rules = knowledge.agency_rules(category)
    departments = [_resolve(d, location, nearby) for d in rules["departments"]]
    data = {
        "departments": departments,
        "channels": knowledge.channels(rules["channels"]),
        "procedure": rules["procedure"],
        "evidence": rules["evidence"],
        "period": rules["period"],
    }
    summary = " / ".join(f"{d['agency']} {d['unit']}" for d in departments)
    specific = all(d["source"] != "kb" for d in departments)
    return tool_result("kb_lookup", True, "kb" if not specific else "kb+region", summary, data)
