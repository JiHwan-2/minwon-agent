"""진행 중인 처리 멈추기: 세션별 중단 요청을 기록하고, 실행 중인 claude 프로세스를 바로 끝낸다.

처리는 서버 스레드에서 돌고 중단 요청은 다른 요청(스레드)으로 들어오므로 잠금으로 보호한다.
지금 어느 세션을 처리하는지는 LangGraph 설정(configurable.session_id)이나 scope()로 알아낸다.
"""

import threading
from contextlib import contextmanager
from contextvars import ContextVar

from langgraph.config import get_config


class Cancelled(Exception):
    """사용자가 중단을 눌렀다. 규칙 엔진으로 대체하지 않고 이번 처리 전체를 멈춘다."""


_lock = threading.Lock()
_active: set[str] = set()
_requested: set[str] = set()
_processes: dict[str, set] = {}
_scope: ContextVar[str] = ContextVar("cancel_scope", default="")


def current() -> str:
    """지금 처리 중인 세션 id (그래프 밖·테스트에서는 빈 문자열)."""
    if scoped := _scope.get():
        return scoped
    try:
        return get_config().get("configurable", {}).get("session_id", "")
    except RuntimeError:
        return ""


@contextmanager
def scope(session_id: str):
    """그래프 밖에서 판단 엔진을 부를 때 어느 세션 처리인지 알려 준다."""
    token = _scope.set(session_id)
    try:
        yield
    finally:
        _scope.reset(token)


def begin(session_id: str) -> None:
    with _lock:
        _active.add(session_id)
        _requested.discard(session_id)


def finish(session_id: str) -> None:
    with _lock:
        _active.discard(session_id)
        _requested.discard(session_id)
        _processes.pop(session_id, None)


def request(session_id: str) -> bool:
    """중단 요청. 처리 중이었으면 True. 실행 중인 claude 프로세스는 바로 끝낸다."""
    with _lock:
        if session_id not in _active:
            return False
        _requested.add(session_id)
        processes = list(_processes.get(session_id, ()))
    for proc in processes:
        try:
            proc.kill()
        except OSError:
            pass  # 이미 끝난 프로세스
    return True


def requested(session_id: str) -> bool:
    with _lock:
        return session_id in _requested


def check() -> None:
    """중단 요청이 들어왔으면 Cancelled를 일으킨다 (단계 시작·외부 호출 직전에 부름)."""
    if (session_id := current()) and requested(session_id):
        raise Cancelled()


@contextmanager
def running(proc):
    """실행 중인 프로세스를 등록해 두어 중단 요청 때 끝낼 수 있게 한다."""
    session_id = current()
    with _lock:
        _processes.setdefault(session_id, set()).add(proc)
    try:
        yield
    finally:
        with _lock:
            _processes.get(session_id, set()).discard(proc)
