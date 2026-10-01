def tool_result(tool: str, ok: bool, source: str, summary: str, data, attempts: int = 0, error: str = "") -> dict:
    """모든 Tool이 같은 모양으로 결과를 돌려준다 (실행 로그·화면 표시용)."""
    return {"tool": tool, "ok": ok, "source": source, "summary": summary, "data": data,
            "attempts": attempts, "error": error}
