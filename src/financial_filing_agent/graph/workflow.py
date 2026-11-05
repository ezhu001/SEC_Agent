from langgraph.graph import StateGraph, START, END
from ..schemas.state import RunState
from .routing import route


def build_graph(nodes):
    builder = StateGraph(RunState)
    names = ["validate_request", "load_filing", "plan_task", "build_evidence", "check_inputs", "retrieve_component",
             "assess_sufficiency", "expand_search", "verify", "guard", "correct", "next_component", "calculate", "finish"]
    for name in names:
        builder.add_node(name, nodes[name])
    builder.add_edge(START, "validate_request")
    allowed = {
        "validate_request": ["load_filing", "finish"],
        "load_filing": ["plan_task", "finish"],
        "plan_task": ["build_evidence", "finish"],
        "build_evidence": ["check_inputs", "finish"],
        "check_inputs": ["retrieve_component", "finish"],
        "retrieve_component": ["assess_sufficiency", "finish"],
        "assess_sufficiency": ["verify", "expand_search", "finish"],
        "expand_search": ["assess_sufficiency", "finish"],
        "verify": ["guard", "correct", "finish"],
        "guard": ["next_component", "correct", "finish"],
        "correct": ["verify", "expand_search", "correct", "finish"],
        "next_component": ["retrieve_component", "calculate", "finish"],
        "calculate": ["correct", "finish"],
    }
    for name, destinations in allowed.items():
        builder.add_conditional_edges(name, route, {n: n for n in destinations})
    builder.add_edge("finish", END)
    return builder.compile()
