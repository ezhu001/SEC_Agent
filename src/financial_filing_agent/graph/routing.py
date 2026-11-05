def route(state):
    return "finish" if state.get("final_status") else state["route"]
