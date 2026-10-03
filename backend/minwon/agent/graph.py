from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from minwon.agent import nodes
from minwon.agent.state import AgentState

NODE_ORDER = ["guard", "look", "confirm_photo", "understand", "chat", "plan", "check", "ask", "locate", "confirm_location", "act",
              "decide", "draft", "review", "translate", "deliver"]


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)
    for name in NODE_ORDER:
        g.add_node(name, getattr(nodes, name))

    g.add_conditional_edges(START, nodes.route_entry, {"guard": "guard", "draft": "draft"})
    # 사진을 올렸으면: 사진 분석 → 예/아니요 확인 → (확인한 내용으로) 문제 분석
    g.add_conditional_edges("guard", nodes.route_after_guard, {"look": "look", "understand": "understand"})
    g.add_conditional_edges("look", nodes.route_after_look, {"confirm_photo": "confirm_photo", "understand": "understand"})
    g.add_conditional_edges("confirm_photo", nodes.route_after_confirm_photo, {"confirm_photo": "confirm_photo", "understand": "understand"})
    g.add_conditional_edges("understand", nodes.route_after_understand, {"plan": "plan", "chat": "chat", "end": END})
    g.add_edge("chat", END)
    g.add_edge("plan", "check")
    g.add_conditional_edges("check", nodes.route_after_check, {"ask": "ask", "locate": "locate", "act": "act"})
    g.add_edge("ask", "check")
    g.add_conditional_edges("locate", nodes.route_after_locate, {"confirm_location": "confirm_location", "act": "act"})
    g.add_conditional_edges("confirm_location", nodes.route_after_confirm, {"locate": "locate", "act": "act"})
    g.add_edge("act", "decide")
    g.add_edge("decide", "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", nodes.route_after_review, {"draft": "draft", "translate": "translate", "deliver": "deliver"})
    g.add_edge("translate", "deliver")
    g.add_edge("deliver", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def start_input(masked_text: str, pii_findings: list[dict], lang_hint: str = "",
                chat_history: list[dict] | None = None, latest: str = "", photo: dict | None = None) -> dict:
    return {
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
