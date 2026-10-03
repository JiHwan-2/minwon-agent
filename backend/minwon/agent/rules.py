"""Claude Code를 쓰지 않거나 호출이 실패했을 때 쓰는 규칙 기반 판단 엔진."""

import re

from minwon import i18n, knowledge
from minwon.tools import regions
from minwon.agent.schemas import (
    Critique,
    Decision,
    Draft,
    EvidenceItem,
    Fact,
    InfoCheck,
    Plan,
    PlanStep,
    Question,
    TopicCheck,
    Translation,
    Understanding,
)

DANGER = re.compile(r"(위험|사고|다칠|다쳤|넘어|아이들|어린이|노인|싱크홀|무너)")

REGIONS = [
    "창원", "마산", "진해", "진주", "통영", "사천", "김해", "밀양", "거제", "양산", "의령", "함안",
    "창녕", "고성", "남해", "하동", "산청", "함양", "거창", "합천",
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
]
DISTRICT = re.compile(r"[가-힣]{2,5}(?:시|군|구|동|읍)(?=\s|$|[,.에의])")
NOT_DISTRICT = {"하수구", "배수구", "출입구", "비상구", "환기구", "통풍구", "놀이기구", "운동기구", "공동", "자동"}
LANDMARK = re.compile(
    r"[가-힣A-Za-z0-9]*(?:초등학교|중학교|고등학교|대학교|학교|아파트|빌라|공원|놀이터|시장|사거리|삼거리|"
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
# 규칙 엔진은 '그리고·이번엔·그게 아니라'처럼 화제를 바꾸는 말이 있을 때만 새 민원으로 본다 (답변 속 시설 이름 오인 방지)
SWITCH_CUE = re.compile(r"(그리고|그런데|근데|이번엔|이번에는|다른|또 |또한|추가로|새로|말고|아니라|아니고)")
SHORTER = re.compile(r"(짧|간단|줄여|요약)")


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
    landmarks = [m.group(0) for m in LANDMARK.finditer(text)]
    named = [lm for lm in landmarks if regions.is_specific_place(lm)]
    generic = max(landmarks, key=len) if landmarks else None  # '학교'보다 '초등학교'
    if place := (named[0] if named else None) or next(iter(ROAD_ADDRESS.findall(text)), None) or generic:
        parts.append(place)
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
            intent="complaint",  # 민원 여부·다른 창구 판단은 Claude만 한다. 대체 경로에서는 기존처럼 민원으로 진행
            referral="none",
            language=i18n.detect(text) or "ko",  # 글자 모양으로 알 수 있는 언어만. 모르면 한국어
            reply="",
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
            PlanStep(action="case_search", title="비슷한 민원 사례 조회", reason="공공데이터에서 같은 유형의 민원을 어느 기관이 처리했는지 확인합니다."),
            PlanStep(action="write", title="민원 초안 작성", reason="모은 정보로 제출할 민원과 증빙 목록을 만듭니다."),
            PlanStep(action="review", title="초안 검증", reason="빠진 사실이나 개인정보가 없는지 확인합니다."),
            PlanStep(action="deliver", title="결과물 만들기", reason="검증한 민원 패키지를 PDF 파일로 만듭니다."),
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
                slots = turn.get("slots", [])
                for slot in slots:
                    if slot in facts:
                        continue
                    # '모름'은 확인된 답으로 본다. 질문이 하나뿐이면 답 전체가 그 항목의 답이다.
                    # 여러 개를 물었는데 그 항목 표현이 없으면 지어내지 않고 미확인으로 남긴다.
                    if UNKNOWN.match(answer) or (len(slots) == 1 and len(answer) >= 2):
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

    def decide(self, ctx: dict) -> Decision:
        channels = ctx["channels"]
        channel = next((c for c in channels if c["url"]), channels[0])
        primary = ctx["departments"][0]
        cautions = []
        if len(ctx["departments"]) > 1:
            other = ctx["departments"][1]
            cautions.append(f"{other['agency']}({other['unit']})도 관련 업무를 맡고 있어, 필요하면 함께 이송될 수 있습니다.")
        return Decision(
            primary=0,
            channel_id=channel["id"],
            reason=f"{primary['unit']}가 '{primary['duty']}' 업무를 맡고 있어 {primary['agency']}에 제출합니다.",
            steps=ctx["procedure"],
            cautions=cautions,
            relevant_cases=list(range(len(ctx.get("similar_cases", [])))),  # 규칙 엔진은 관련성을 판단하지 않고 모두 유지
        )

    def write(self, ctx: dict) -> Draft:
        facts = {f["slot"]: f["value"] for f in ctx["facts"]}
        loc = ctx["location"]
        place = loc.get("place_name") or facts.get("location", "")
        address = loc.get("address") or facts.get("location", "[위치]")
        where = f"{address} ({place})" if place and place not in address else address
        label = ctx["understanding"]["category_label"]
        area = loc.get("sigungu") or "우리 동네"

        greeting = f"안녕하십니까. {where} 인근의 {label} 관련 불편을 알려드리고 개선을 요청드립니다."
        revision = ctx.get("revision_request", "")
        wants_short = bool(revision and SHORTER.search(revision))

        if wants_short:
            lines = [greeting, f"위치는 {where}이며, {ctx['understanding']['summary']}", ctx["kb"]["request"], "검토 부탁드립니다."]
        else:
            lines = [greeting, "", "1. 현황", f"- 위치: {where}", f"- 발생 시기: {facts.get('time', '[언제 주로 발생하는지]')}"]
            if "frequency" in facts or "frequency" in ctx["required_info"]:
                lines.append(f"- 반복 여부: {facts.get('frequency', '[얼마나 자주 반복되는지]')}")
            lines.append(f"- 상황: {ctx['understanding']['summary']}")
            if "target" in facts:
                lines.append(f"- 원인 대상: {facts['target']}")
            if "harm" in facts:
                lines.append(f"- 위험·피해: {facts['harm']}")
            lines += ["", "2. 요청 사항", ctx["kb"]["request"]]
            if revision:
                lines.append(f"추가로, {revision.rstrip('.')}.")
            lines += ["", "현장 사진 등 증빙자료를 함께 첨부합니다. 검토해 주셔서 감사합니다."]

        evidence = [EvidenceItem(**e) for e in ctx["kb"]["evidence"]]
        if "harm" in facts and not any(e.level == "separate" for e in evidence):
            evidence.append(EvidenceItem(
                item="피해 사진·진료 기록·수리 영수증",
                level="separate",
                why="피해 보상은 개선 민원과 별도 절차(배상 청구)로 신청해요. 담당 부서에 절차를 문의하세요.",
                basis="",
            ))
        return Draft(
            title=f"[{area}] {place or label} {label} 개선 요청"[:40],
            body="\n".join(lines),
            evidence=evidence,
            tips=["사진에는 위치를 알 수 있는 간판·건물이 함께 나오게 찍어 주세요.", "접수번호를 메모해 두면 처리 상황을 조회할 수 있습니다."],
        )

    def critique(self, ctx: dict) -> Critique:
        return Critique(passed=True, issues=[])

    def switch(self, ctx: dict) -> TopicCheck:
        current = ctx["current"]["category"]
        message = ctx["message"]
        found = classify(message)
        current_keywords = knowledge.category(current)["keywords"]
        new = (found not in (current, "other") and SWITCH_CUE.search(message) is not None
               and not any(kw in message for kw in current_keywords))
        reason = (f"화제를 바꾸는 말과 함께 '{knowledge.category(found)['label']}' 유형의 불편을 새로 말함" if new
                  else "지금 민원에 대한 답변이나 수정 요청으로 봄")
        # 관계없는 말(off_topic)은 규칙으로 판단하지 않는다. Claude가 실패하면 지금 민원에 이어지는 말로 받는다
        return TopicCheck(kind="new_complaint" if new else "continue", category=found if new else current, reason=reason)

    def translate(self, ctx: dict) -> Translation:
        """번역은 규칙으로 할 수 없으니 한국어 원문을 그대로 돌려준다 (화면은 한국어로 보여 줌)."""
        return Translation.model_validate(ctx["source"])
