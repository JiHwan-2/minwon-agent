"""정확도 평가 세트(eval/dataset.json)의 정답 표기가 올바른지 확인한다 (실제 Claude는 부르지 않음)."""

import json
from pathlib import Path

from minwon import i18n, knowledge
from minwon.agent.schemas import CategoryCode, Intent, ReferralCode, TurnKind

DATA = json.loads((Path(__file__).resolve().parents[1] / "eval" / "dataset.json").read_text(encoding="utf-8"))


def _values(v):
    return v if isinstance(v, list) else [v]


def test_ids_are_unique_and_prefixed():
    for part, prefix in (("understand", "URNXSV"), ("turn", "T"), ("e2e", "A")):
        ids = [c["id"] for c in DATA[part]]
        assert len(ids) == len(set(ids)), part
        assert all(i[0] in prefix for i in ids), part


def test_understand_labels_use_real_codes():
    for c in DATA["understand"]:
        assert c.get("intent") or c.get("safety"), c["id"]
        assert all(v in Intent.__args__ for v in _values(c.get("intent", []))), c["id"]
        assert all(v in CategoryCode.__args__ for v in _values(c.get("category", []))), c["id"]
        if "referral" in c:
            assert c["referral"] in ReferralCode.__args__ and c["intent"] == "referral", c["id"]
        if "service" in c:
            assert c["service"] in knowledge.services() and c["intent"] == "service", c["id"]
        assert set(c.get("safety", {})) <= {"pii", "emergency", "crisis", "injection"}, c["id"]
        if "language" in c:
            assert c["language"] in i18n.LANGS, c["id"]


def test_turn_labels_use_real_codes():
    for c in DATA["turn"]:
        assert c["stage"] in ("asking", "ready") and c["kind"] in TurnKind.__args__, c["id"]


def test_e2e_cases_have_full_expectations():
    for c in DATA["e2e"]:
        assert c["category"] in knowledge.categories(), c["id"]
        assert c["sigungu"] and c["agency"] and c["unit"], c["id"]


def test_dataset_covers_every_category_and_judgment():
    complaints = {v for c in DATA["understand"] if c.get("intent") == "complaint" for v in _values(c["category"])}
    assert set(CategoryCode.__args__) - {"other"} <= complaints
    intents = {v for c in DATA["understand"] for v in _values(c.get("intent", []))}
    assert intents == set(Intent.__args__)
    assert {c["referral"] for c in DATA["understand"] if "referral" in c} == set(ReferralCode.__args__) - {"none"}
    groups = {knowledge.service(c["service"])["group"] for c in DATA["understand"] if "service" in c}
    assert groups == set(knowledge.service_groups())  # 증명서·신청신고·생활 행정·복지를 모두 묻는다
    assert {c["kind"] for c in DATA["turn"]} == set(TurnKind.__args__)
