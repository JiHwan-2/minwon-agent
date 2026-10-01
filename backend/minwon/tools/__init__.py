def tool_result(tool: str, ok: bool, source: str, summary: str, data, retries: int = 0, error: str = "") -> dict:
    """모든 Tool이 같은 모양으로 결과를 돌려준다 (실행 로그·화면 표시용). retries는 일시 오류로 다시 시도한 횟수."""
    return {"tool": tool, "ok": ok, "source": source, "summary": summary, "data": data,
            "retries": retries, "error": error}
