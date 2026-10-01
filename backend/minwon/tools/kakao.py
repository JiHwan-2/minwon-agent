"""카카오 로컬 API 호출 (일시적 오류는 1회 재시도)."""

import time

import httpx

from minwon.settings import settings

BASE = "https://dapi.kakao.com/v2/local"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class KakaoError(Exception):
    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


def api_key() -> str:
    return settings.kakao_rest_api_key


def _explain(resp: httpx.Response) -> str:
    if resp.status_code == 401:
        return "카카오 API 키가 올바르지 않습니다"
    if resp.status_code == 403:
        return "카카오맵(로컬) 사용 설정이 꺼져 있거나 권한이 없습니다"
    return f"카카오 API 오류 (HTTP {resp.status_code})"


def request(path: str, params: dict, retries: int = 1) -> tuple[dict, int]:
    """(응답 JSON, 시도 횟수)를 돌려준다. 실패하면 KakaoError."""
    if not api_key():
        raise KakaoError("카카오 API 키가 설정되지 않았습니다", attempts=0)
    attempts = 0
    while True:
        attempts += 1
        try:
            resp = httpx.get(
                f"{BASE}/{path}",
                params=params,
                headers={"Authorization": f"KakaoAK {api_key()}"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                return resp.json(), attempts
            if resp.status_code not in RETRYABLE_STATUS or attempts > retries:
                raise KakaoError(_explain(resp), attempts)
        except httpx.TransportError as e:
            if attempts > retries:
                raise KakaoError(f"카카오 API 연결 실패 ({type(e).__name__})", attempts) from e
        time.sleep(0.4)


def keyword(query: str, size: int = 1, **near) -> tuple[list[dict], int]:
    data, attempts = request("search/keyword.json", {"query": query, "size": size, **near})
    return data.get("documents", []), attempts


def address(query: str) -> tuple[list[dict], int]:
    data, attempts = request("search/address.json", {"query": query, "size": 1})
    return data.get("documents", []), attempts


def region(x: str, y: str) -> tuple[list[dict], int]:
    data, attempts = request("geo/coord2regioncode.json", {"x": x, "y": y})
    return data.get("documents", []), attempts
