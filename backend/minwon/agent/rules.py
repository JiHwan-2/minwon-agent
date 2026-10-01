"""API 키가 없거나 LLM 호출이 실패했을 때 쓰는 규칙 기반 판단 엔진."""

import re

from minwon import knowledge
from minwon.agent.schemas import Fact, InfoCheck, Plan, PlanStep, Question, Understanding

DANGER = re.compile(r"(위험|사고|다칠|다쳤|넘어|아이들|어린이|노인|싱크홀|무너)")

REGIONS = [
    "창원", "마산", "진해", "진주", "통영", "사천", "김해", "밀양", "거제", "양산", "의령", "함안",
    "창녕", "고성", "남해", "하동", "산청", "함양", "거창", "합천",
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
]
DISTRICT = re.compile(r"[가-힣]{2,5}(?:시|군|구|동|읍)(?=\s|$|[,.에의])")
NOT_DISTRICT = {"하수구", "배수구", "출입구", "비상구", "환기구", "통풍구", "놀이기구", "운동기구", "공동", "자동"}
LANDMARK = re.compile(
    r"[가-힣A-Za-z0-9]+(?:초등학교|중학교|고등학교|대학교|학교|아파트|빌라|역|공원|시장|사거리|삼거리|"
    r"오거리|교차로|정류장|병원|마트|주민센터|행정복지센터|도서관|체육관|상가|빌딩)"
)
ROAD_ADDRESS = re.compile(r"[가-힣0-9]+(?:로|길)\s?\d+(?:-\d+)?")
TIME = re.compile(
    r"(\d{1,2}\s?시(?:\s?\d{1,2}\s?분)?|오전|오후|아침|점심|저녁|밤(?!나무)|새벽|낮(?![은게아])|등하교|등교|하교|"
    r"출근|퇴근|주말|평일|[월화수목금토일]요일|어제|오늘|그저께|지난주)"
)
FREQUENCY = re.compile(r"(매일|날마다|자주|항상|계속|반복|[가-힣]+마다|수시로|가끔|처음|한 번)")
HARM = re.compile(r"(다쳤|부상|사고가 났|넘어졌|피해를|아파|병원에)")
TARGET = re.compile(r"(\d{2,3}[가-힣]\s?\d{4}|\d+번\s?버스|[가-힣A-Za-z0-9]+(?:건설|산업|업체|식당|노래방|술집|공장))")
UNKNOWN = re.compile(r"^(모름|몰라요|모르겠어요|잘 모르겠|없음|없어요)")


def classify(text: str) -> str:
    scores = {
        code: sum(kw in text for kw in cat["keywords"])
        for code, cat in knowledge.categories().items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def find_location(text: str) -> str:
    parts = [r for r in REGIONS if r in text][:1]
    parts += [d for d in DISTRICT.findall(text) if d not in NOT_DISTRICT][:3]
    if m := (LANDMARK.search(text) or ROAD_ADDRESS.search(text)):
        parts.append(m.group(0))
    return " ".join(dict.fromkeys(p for p in parts if not any(p != q and p in q for q in parts)))


def extract_facts(texts: list[str]) -> dict[str, str]:
    joined = " ".join(texts)
    facts: dict[str, str] = {}
    if loc := find_location(joined):
        facts["location"] = loc
    for slot, pattern in (("time", TIME), ("frequency", FREQUENCY), ("harm", HARM), ("target", TARGET)):
        found = list(dict.fromkeys(pattern.findall(joined)))
        if found:
            facts[slot] = " ".join(found)
    if texts and len(texts[0]) >= 12:
        facts["detail"] = texts[0]
    return facts


class RuleBrain:
    def understand(self, text: str) -> Understanding:
        code = classify(text)
        cat = knowledge.category(code)
        keywords = [kw for kw in cat["keywords"] if kw in text][:5] or [cat["label"]]
        return Understanding(
            category=code,
            title=f"{cat['label']} 불편 신고",
            summary=text.strip()[:200],
            urgency="high" if DANGER.search(text) else "medium" if code != "other" else "low",
            keywords=keywords,
            location_hint=find_location(text),
        )

    def plan(self, ctx: dict) -> Plan:
        cat = knowledge.category(ctx["understanding"]["category"])
        known = extract_facts([ctx["user_input"]])
        missing = [s for s in cat["required"] if s not in known]
        steps = []
        if missing:
            labels = ", ".join(knowledge.slots()[s]["label"] for s in missing)
            steps.append(PlanStep(action="ask_user", title="부족한 정보 질문", reason=f"{labels} 정보가 있어야 담당 기관을 정확히 찾을 수 있습니다."))
        steps.append(PlanStep(action="geocode", title="위치 확인", reason="관할 시·군·구를 정하려면 정확한 주소가 필요합니다."))
        if cat["nearby"]:
            steps.append(PlanStep(action="find_nearby", title="주변 기관 검색", reason="현장을 관할하는 기관을 찾습니다."))
        steps += [
            PlanStep(action="kb_lookup", title="담당 부서·절차 조회", reason=f"{cat['label']} 민원을 처리하는 부서와 제출 창구를 확인합니다."),
            PlanStep(action="write", title="민원 초안 작성", reason="모은 정보로 제출할 민원과 증빙 목록을 만듭니다."),
            PlanStep(action="review", title="초안 검증", reason="빠진 사실이나 개인정보가 없는지 확인합니다."),
        ]
        return Plan(
            goal=f"{cat['label']} 불편을 담당 기관에 정확히 전달할 민원을 준비합니다.",
            steps=steps,
            required_info=list(cat["required"]),
            nearby_kinds=list(cat["nearby"]),
        )

    def check(self, ctx: dict) -> InfoCheck:
        dialogue = ctx["dialogue"]
        user_texts = [d["text"] for d in dialogue if d["role"] == "user"]
        facts = extract_facts(user_texts)
        for i, turn in enumerate(dialogue):
            if turn["role"] == "agent" and i + 1 < len(dialogue):
                answer = dialogue[i + 1]["text"]
                for slot in turn.get("slots", []):
                    if slot not in facts and (len(answer) >= 2 or UNKNOWN.match(answer)):
                        facts[slot] = answer
        questions = []
        if ctx["can_ask"]:
            slot_info = knowledge.slots()
            questions = [
                Question(slot=s, text=slot_info[s]["question"])
                for s in ctx["required_info"]
                if s not in facts and s not in ctx["asked"]
            ][:3]
        return InfoCheck(
            facts=[Fact(slot=k, value=v) for k, v in facts.items()],
            questions=questions,
            location_query=facts.get("location", ""),
        )
