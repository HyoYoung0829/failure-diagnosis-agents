import asyncio
import json
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from failure_diagnosis_agents.state import DiagnosisState, ExpertResult, FailureType

load_dotenv()  # .env의 OPENAI_API_KEY 등을 환경변수로 읽어옴

# TWF만 MCP 경유로 바꿔봄 (비교용). 호출될 때마다 서버 프로세스를 새로 띄움 — stdio라 그럼.
mcp_client = MultiServerMCPClient(
    {
        "rules": {
            "command": "python",
            "args": ["-m", "failure_diagnosis_agents.mcp_server"],
            "transport": "stdio",
        }
    }
)


# LLM이 채워야 할 부분만 담은 작은 스키마. ExpertResult 전체를 시키면 안 됨
# (mcp_fact/retry_count/unresolved는 LLM 몫이 아니라 노드 코드가 관리하는 값이라서).
class ExpertVerdict(BaseModel):
    is_failure: bool = Field(description="이 고장 원인이 실제로 발생했다고 보는지")
    confidence_score: float = Field(description="0~1 사이 확신도")
    reason: str = Field(description="그렇게 판단한 근거")


def is_mismatch(failure_type: FailureType, result: ExpertResult) -> bool:
    # verifier_node랑 graph.py의 라우팅 함수가 똑같이 쓰는 "일치/불일치 판단" 로직. 한 곳에만 둠.
    triggered = result["mcp_fact"]["triggered"]
    if failure_type == "TWF":
        # TWF는 확률적이라 "구간 안인데 정상"은 괜찮음, "구간 밖인데 고장"만 모순
        return bool(result["is_failure"]) and not triggered
    return result["is_failure"] != triggered


def build_expert_result(
    failure_type: FailureType, state: DiagnosisState, fact: dict, verdict: ExpertVerdict
) -> ExpertResult:
    # 4개 전문가 노드가 똑같이 하는 "결과 조립 + 재시도 횟수 이어받기" 로직을 한 곳에 모음
    previous = state["expert_results"].get(failure_type)
    retry_count = (
        (previous["retry_count"] + 1) if previous else 0
    )  # 이전 시도 횟수를 이어받음

    result: ExpertResult = {
        "is_failure": verdict.is_failure,
        "confidence_score": verdict.confidence_score,
        "reason": verdict.reason,
        "mcp_fact": fact,
        "retry_count": retry_count,
        "unresolved": False,
        "unresolved_reason": None,
    }

    if is_mismatch(failure_type, result) and retry_count >= 2:
        # 2번 재시도(총 3번 시도)까지 계속 불일치하면 포기하고 솔직하게 보고
        result["unresolved"] = True
        result["unresolved_reason"] = (
            f"{retry_count + 1}번 시도해도 규칙 계산 결과와 계속 불일치"
        )

    return result


# structured output을 붙인 LLM 인스턴스. 모듈 로드 시 한 번만 만들어서 재사용.
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
    ExpertVerdict
)

# 검증 노드는 구조화된 필드가 아니라 자연어 총평 문장을 만들 거라 구조화 출력 없이 사용
text_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


async def run_expert_via_mcp(
    failure_type: FailureType,
    state: DiagnosisState,
    tool_name: str,
    system_prompt: str,
    human_prompt: str,
) -> ExpertResult:
    # 4개 전문가 노드가 공통으로 하는 "MCP 툴 가져와서 LLM한테 쥐어주고, 호출 요청 오면 대신 실행" 로직을 한 곳에 모음
    tools = await mcp_client.get_tools()
    tool = next(t for t in tools if t.name == tool_name)

    llm_with_tool = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools([tool])
    messages = [SystemMessage(system_prompt), HumanMessage(human_prompt)]

    ai_msg = await llm_with_tool.ainvoke(messages)
    messages.append(ai_msg)

    fact = None
    for tool_call in ai_msg.tool_calls:
        tool_response = await tool.ainvoke(tool_call["args"])
        fact = json.loads(tool_response[0]["text"])
        messages.append(ToolMessage(content=str(fact), tool_call_id=tool_call["id"]))

    assert fact is not None, f"LLM이 {tool_name} 툴을 호출하지 않음"

    verdict: ExpertVerdict = await llm.ainvoke(messages)

    return build_expert_result(failure_type, state, fact, verdict)


async def twf_expert_node(state: DiagnosisState) -> dict:
    tool_wear_time = state["tool_wear_time"]

    result = await run_expert_via_mcp(
        "TWF",
        state,
        tool_name="twf_check",
        system_prompt=(
            "너는 설비 공구마모고장(TWF) 진단 전문가야. "
            "판단하기 전에 반드시 twf_check 툴을 호출해서 규칙 계산 결과를 확인해."
        ),
        human_prompt=f"공구 누적 사용 시간은 {tool_wear_time}분이야.",
    )

    return {"expert_results": {"TWF": result}}


# --------------------------------------------------------------------------------------------------------------


async def hdf_expert_node(state: DiagnosisState) -> dict:
    air_temperature = state["air_temperature"]
    process_temperature = state["process_temperature"]
    rotational_speed = state["rotational_speed"]

    result = await run_expert_via_mcp(
        "HDF",
        state,
        tool_name="hdf_check",
        system_prompt=(
            "너는 설비 방열고장(HDF) 진단 전문가야. "
            "판단하기 전에 반드시 hdf_check 툴을 호출해서 규칙 계산 결과를 확인해."
        ),
        human_prompt=(
            f"대기온도는 {air_temperature}K이고, "
            f"공정온도는 {process_temperature}K이고, "
            f"회전속도는 {rotational_speed}rpm이야."
        ),
    )

    return {"expert_results": {"HDF": result}}


# --------------------------------------------------------------------------------------------------------------


async def pwf_expert_node(state: DiagnosisState) -> dict:
    torque = state["torque"]
    rotational_speed = state["rotational_speed"]

    result = await run_expert_via_mcp(
        "PWF",
        state,
        tool_name="pwf_check",
        system_prompt=(
            "너는 설비 동력고장(PWF) 진단 전문가야. "
            "판단하기 전에 반드시 pwf_check 툴을 호출해서 규칙 계산 결과를 확인해."
        ),
        human_prompt=f"토크는 {torque}Nm이고, 회전속도는 {rotational_speed}rpm이야.",
    )

    return {"expert_results": {"PWF": result}}


# --------------------------------------------------------------------------------------------------------------


async def osf_expert_node(state: DiagnosisState) -> dict:
    tool_wear_time = state["tool_wear_time"]
    torque = state["torque"]
    product_type = state["type"]  # 내장함수 type()과 이름 겹치는 걸 피하려고 개명

    result = await run_expert_via_mcp(
        "OSF",
        state,
        tool_name="osf_check",
        system_prompt=(
            "너는 설비 과응력고장(OSF) 진단 전문가야. "
            "판단하기 전에 반드시 osf_check 툴을 호출해서 규칙 계산 결과를 확인해."
        ),
        human_prompt=(
            f"공구 누적 사용 시간은 {tool_wear_time}min이고, "
            f"토크는 {torque}Nm이고, "
            f"제품 등급은 {product_type}이야."
        ),
    )

    return {"expert_results": {"OSF": result}}


# --------------------------------------------------------------------------------------------------------------


def verifier_node(state: DiagnosisState) -> dict:
    expert_results = state[
        "expert_results"
    ]  # 1. 4명(또는 그중 완료된) 결과를 통째로 읽음

    # 2. 확신도 내림차순 정렬. 정렬 자체는 그냥 파이썬 로직이라 LLM한테 안 시킴
    sorted_results = sorted(
        expert_results.items(),
        key=lambda item: item[1]["confidence_score"],
        reverse=True,
    )

    lines = []
    for failure_type, result in sorted_results:
        if result[
            "unresolved"
        ]:  # 3. 재시도 2회 넘게 실패한 전문가는 판정 불가로 그대로 보고
            lines.append(
                f"- {failure_type}: 판정 불가 (사유: {result['unresolved_reason']})"
            )
            continue

        mismatch = is_mismatch(failure_type, result)

        lines.append(
            f"- {failure_type}: 판정={result['is_failure']}, 확신도={result['confidence_score']:.2f}, "
            f"규칙 계산과 {'불일치(재확인 필요)' if mismatch else '일치'}, 근거={result['reason']}"
        )

    prompt = (  # 4. 이미 계산된 일치/불일치 사실을 그대로 주고, LLM은 요약 문장만 작성
        "너는 설비 고장진단 검증 책임자야. 아래는 각 고장 원인 전문가들의 판정을 확신도 순으로 정렬한 것이다.\n"
        + "\n".join(lines)
        + "\n이 내용을 바탕으로 가장 유력한 고장 원인이 무엇인지와 어떤 부품/요소를 확인해야 하는지 "
        "한두 문장으로 총평을 작성해. 규칙과 불일치하거나 판정 불가한 전문가가 있으면 그 사실도 솔직하게 언급해."
    )

    overall_assessment = text_llm.invoke(
        prompt
    ).content  # 5. 자연어 총평 생성 (구조화 출력 아님)

    return {"overall_assessment": overall_assessment}  # 6. 바뀐 필드만 반환


async def _main() -> None:
    # 수동 확인용: 실제 LLM 호출이 여러 번 들어가므로 OPENAI_API_KEY 필요
    sample_state: DiagnosisState = {
        "case_id": 1,
        "type": "M",
        "air_temperature": 298.1,
        "process_temperature": 308.6,
        "rotational_speed": 1551,
        "torque": 42.8,
        "tool_wear_time": 220,  # 200~240 구간 안 (TWF 가능 구간)
        "expert_results": {},
        "overall_assessment": None,
    }

    # 아직 그래프로 안 묶었으니 노드들을 수동으로 순서대로 호출해서 State를 직접 합쳐봄
    # 이제 4개 다 MCP 경유(async)라 전부 await
    state = dict(sample_state)
    for node in (twf_expert_node, hdf_expert_node, pwf_expert_node, osf_expert_node):
        update = await node(state)
        state["expert_results"] = {
            **state["expert_results"],
            **update["expert_results"],
        }

    print(verifier_node(state)["overall_assessment"])


if __name__ == "__main__":
    asyncio.run(
        _main()
    )  # 여기는 최상위 진입점이라 asyncio.run()을 써도 안전함 (중첩 루프 아님)
