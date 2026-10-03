from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from minwon.agent import nodes
from minwon.agent.state import AgentState

NODE_ORDER = ["guard", "look", "confirm_photo", "understand", "chat", "plan", "check", "ask", "locate", "confirm_location", "act",
              "decide", "draft", "review", "translate", "deliver", "svc_plan", "svc_check", "svc_act", "svc_answer"]


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)
    for name in NODE_ORDER:
        g.add_node(name, getattr(nodes, name))

    g.add_conditional_edges(START, nodes.route_entry, {"guard": "guard", "draft": "draft"})
    # 사진을 올렸으면: 사진 분석 → 예/아니요 확인 → (확인한 내용으로) 문제 분석
    g.add_conditional_edges("guard", nodes.route_after_guard, {"look": "look", "understand": "understand"})
    g.add_conditional_edges("look", nodes.route_after_look, {"confirm_photo": "confirm_photo", "understand": "understand"})
    g.add_conditional_edges("confirm_photo", nodes.route_after_confirm_photo, {"confirm_photo": "confirm_photo", "understand": "understand"})
    g.add_conditional_edges("understand", nodes.route_after_understand,
                            {"plan": "plan", "svc_plan": "svc_plan", "chat": "chat", "end": END})
    g.add_edge("chat", END)
    g.add_edge("plan", "check")
    g.add_conditional_edges("check", nodes.route_after_check, {"ask": "ask", "locate": "locate", "act": "act"})
    g.add_conditional_edges("ask", nodes.route_after_ask, {"check": "check", "svc_check": "svc_check"})
    after_location = {"act": "act", "svc_act": "svc_act"}
    g.add_conditional_edges("locate", nodes.route_after_locate, {"confirm_location": "confirm_location", **after_location})
    g.add_conditional_edges("confirm_location", nodes.route_after_confirm, {"locate": "locate", **after_location})
    # 민원 서비스 안내 (서류 발급·신고·신청): 계획 → 필요한 정보 ⇄ 질문 → 위치 → 기관·발급기·운영 여부 → 안내
    g.add_edge("svc_plan", "svc_check")
    g.add_conditional_edges("svc_check", nodes.route_after_svc_check, {"ask": "ask", "locate": "locate", "svc_act": "svc_act"})
    g.add_edge("svc_act", "svc_answer")
    g.add_edge("svc_answer", END)
    g.add_edge("act", "decide")
    g.add_edge("decide", "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", nodes.route_after_review, {"draft": "draft", "translate": "translate", "deliver": "deliver"})
    g.add_edge("translate", "deliver")
    g.add_edge("deliver", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def start_input(masked_text: str, pii_findings: list[dict], lang_hint: str = "",
                chat_history: list[dict] | None = None, latest: str = "", photo: dict | None = None,
                location: dict | None = None) -> dict:
    """location: 민원 서비스 안내에 이어서 묻는 말이면 앞에서 확정한 위치 (다시 묻지 않게)."""
    kept = {"location": location, "location_confirmed": True} if location else {"location": {}, "location_confirmed": False}
    return {
        **kept,
        "user_input": masked_text,
        "latest": latest or masked_text,
        "chat_history": chat_history or [],
        "pii_findings": pii_findings,
        "lang_hint": lang_hint,
        "photo": photo or {},
        # 사진이 있으면 첫 대화 기록은 사진 확인을 마친 뒤 확인한 내용으로 남긴다 (nodes._photo_text)
        "dialogue": [] if photo else [{"role": "user", "text": masked_text}],
        "asked": [],
        "rounds": 0,
        "tool_calls": [],
        "location_query": "",
        "confirm_rounds": 0,
        "review_rounds": 0,
        "revision_request": "",
        "log": [],
    }


def revision_input(masked_text: str) -> dict:
    return {
        "revision_request": masked_text,
        "review_rounds": 0,
        "dialogue": [{"role": "user", "text": masked_text, "kind": "revision"}],
    }
