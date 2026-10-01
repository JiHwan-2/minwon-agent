import json
from functools import cache
from pathlib import Path

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
