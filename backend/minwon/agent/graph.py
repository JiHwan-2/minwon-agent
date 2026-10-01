from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from minwon.agent import nodes
from minwon.agent.state import AgentState

NODE_ORDER = ["guard", "understand", "plan", "check", "ask", "act", "decide", "draft", "review"]


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)
    for name in NODE_ORDER:
        g.add_node(name, getattr(nodes, name))

    g.add_conditional_edges(START, nodes.route_entry, {"guard": "guard", "draft": "draft"})
    g.add_edge("guard", "understand")
    g.add_edge("understand", "plan")
    g.add_edge("plan", "check")
    g.add_conditional_edges("check", nodes.route_after_check, {"ask": "ask", "act": "act"})
    g.add_edge("ask", "check")
    g.add_edge("act", "decide")
    g.add_edge("decide", "draft")
    g.add_edge("draft", "review")
    g.add_conditional_edges("review", nodes.route_after_review, {"draft": "draft", "done": END})
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def start_input(masked_text: str, pii_findings: list[dict]) -> dict:
    return {
        "user_input": masked_text,
        "pii_findings": pii_findings,
        "dialogue": [{"role": "user", "text": masked_text}],
        "asked": [],
        "rounds": 0,
        "tool_calls": [],
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
