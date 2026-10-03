import json
from functools import cache
from pathlib import Path

from minwon import i18n

_DIR = Path(__file__).resolve().parent


@cache
def _load() -> dict:
    return json.loads((_DIR / "categories.json").read_text(encoding="utf-8"))


@cache
def _agencies() -> dict:
    return json.loads((_DIR / "agencies.json").read_text(encoding="utf-8"))


def agency_rules(code: str) -> dict:
    cats = _agencies()["categories"]
    return cats.get(code, cats["other"])


def all_channels() -> dict[str, dict]:
    return _agencies()["channels"]


def channels(ids: list[str]) -> list[dict]:
    all_channels = _agencies()["channels"]
    return [{"id": cid, **all_channels[cid]} for cid in ids]


def slots() -> dict[str, dict]:
    return _load()["slots"]


def categories() -> dict[str, dict]:
    return _load()["categories"]


def category(code: str) -> dict:
    cats = categories()
    return cats.get(code, cats["other"])


def category_guide() -> str:
    return "\n".join(f"- {code}: {c['label']} ({c['examples']})" for code, c in categories().items())


def referrals() -> dict[str, dict]:
    """시·군·구청 민원이 아니라 다른 공식 창구가 해결하는 일 (소비자 피해·임금체불·사기·개인 간 분쟁)."""
    return {code: r for code, r in _agencies()["referrals"].items() if not code.startswith("_")}


def referral(code: str, lang: str = "ko") -> dict:
    """다른 창구 안내 카드. 번역해 둔 언어면 그 언어로 (번호·주소는 원문 그대로)."""
    return i18n.referral(code, lang, {"code": code, **referrals()[code]})


def referral_guide() -> str:
    return "\n".join(f"- {code}: {r['label']} ({r['examples']}) → {r['agency']}" for code, r in referrals().items())
