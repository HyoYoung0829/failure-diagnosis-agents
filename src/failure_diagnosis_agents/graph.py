from langgraph.graph import StateGraph, START, END

from failure_diagnosis_agents.nodes import (
    twf_expert_node,
    pwf_expert_node,
    osf_expert_node,
    hdf_expert_node,
    verifier_node,
    is_mismatch,
)
from failure_diagnosis_agents.state import DiagnosisState

# failure_type -> 재시도 걸 때 돌아갈 노드 이름
NODE_NAME = {
    "TWF": "twf_agent",
    "HDF": "hdf_agent",
    "PWF": "pwf_agent",
    "OSF": "osf_agent",
}


def routing_function(state: DiagnosisState):
    # verifier 다음에 어디로 갈지 결정. state 전체가 아니라 expert_results를 한 명씩 펼쳐봐야 함
    retry_targets = []
    for failure_type, result in state["expert_results"].items():
        if result["unresolved"]:
            continue  # 이미 포기한 전문가는 더 재시도 안 시킴
        if is_mismatch(failure_type, result):
            retry_targets.append(NODE_NAME[failure_type])

    return retry_targets if retry_targets else END  # 재시도할 게 있으면 그 노드(들)로, 없으면 종료


builder = StateGraph(DiagnosisState)
builder.add_node("twf_agent", twf_expert_node)
builder.add_node("pwf_agent", pwf_expert_node)
builder.add_node("osf_agent", osf_expert_node)
builder.add_node("hdf_agent", hdf_expert_node)
builder.add_node("verifier_agent", verifier_node)

builder.add_edge(START, "twf_agent")
builder.add_edge(START, "pwf_agent")
builder.add_edge(START, "osf_agent")
builder.add_edge(START, "hdf_agent")

builder.add_edge("twf_agent", "verifier_agent")
builder.add_edge("pwf_agent", "verifier_agent")
builder.add_edge("osf_agent", "verifier_agent")
builder.add_edge("hdf_agent", "verifier_agent")

builder.add_conditional_edges("verifier_agent", routing_function)

graph = builder.compile()
