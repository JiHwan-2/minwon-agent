from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from minwon.agent import nodes
from minwon.agent.state import AgentState

NODE_ORDER = ["guard", "understand", "plan", "check", "ask"]


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)
    for name in NODE_ORDER:
        g.add_node(name, getattr(nodes, name))

    g.add_edge(START, "guard")
    g.add_edge("guard", "understand")
    g.add_edge("understand", "plan")
    g.add_edge("plan", "check")
    g.add_conditional_edges("check", nodes.route_after_check, {"ask": "ask", "done": END})
    g.add_edge("ask", "check")
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def start_input(masked_text: str, pii_findings: list[dict]) -> dict:
    return {
        "user_input": masked_text,
        "pii_findings": pii_findings,
        "dialogue": [{"role": "user", "text": masked_text}],
        "asked": [],
        "rounds": 0,
        "log": [],
    }
