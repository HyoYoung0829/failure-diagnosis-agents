import math
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from failure_diagnosis_agents.rules import check_twf, check_hdf, check_pwf, check_osf
from failure_diagnosis_agents.state import DiagnosisState, ExpertResult, FailureType

load_dotenv()  # .env의 OPENAI_API_KEY 등을 환경변수로 읽어옴


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
    retry_count = (previous["retry_count"] + 1) if previous else 0  # 이전 시도 횟수를 이어받음

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
        result["unresolved_reason"] = f"{retry_count + 1}번 시도해도 규칙 계산 결과와 계속 불일치"

    return result


# structured output을 붙인 LLM 인스턴스. 모듈 로드 시 한 번만 만들어서 재사용.
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
    ExpertVerdict
)

# 검증 노드는 구조화된 필드가 아니라 자연어 총평 문장을 만들 거라 구조화 출력 없이 사용
text_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


def twf_expert_node(state: DiagnosisState) -> dict:
    tool_wear_time = state["tool_wear_time"]  # 1. TWF 판단에 필요한 값만 State에서 꺼냄

    fact = check_twf(
        tool_wear_time
    )  # 2. 규칙 함수로 계산된 사실 확보 (나중엔 MCP 툴 호출로 대체될 자리)

    prompt = (
        "너는 설비 공구마모고장(TWF) 진단 전문가야. "
        f"공구 누적 사용 시간은 {tool_wear_time}분이고, "
        f"규칙 계산 결과 고장 가능 구간(200~240분) 해당 여부는 {fact['triggered']}야. "
        "이 정보를 바탕으로 고장 여부, 확신도, 근거를 판단해."
    )
    verdict: ExpertVerdict = llm.invoke(
        prompt
    )  # 3. LLM에게 사실+원시값을 주고 구조화된 판정을 받음

    result = build_expert_result("TWF", state, fact, verdict)  # 4. 결과 조립 (재시도 횟수 이어받기 포함)

    return {
        "expert_results": {"TWF": result}
    }  # 5. State 전체가 아니라 "바뀐 부분만" 반환 → reducer가 merge


# --------------------------------------------------------------------------------------------------------------


def hdf_expert_node(state: DiagnosisState) -> dict:
    air_temperature = state["air_temperature"]
    process_temperature = state["process_temperature"]
    rotational_speed = state["rotational_speed"]

    fact = check_hdf(air_temperature, process_temperature, rotational_speed)

    prompt = (
        "너는 설비 방열고장(HDF) 진단 전문가야. "
        f"대기온도는 {air_temperature}K이고, "
        f"공정온도는 {process_temperature}K이고,"
        f"회전속도는 {rotational_speed}rpm이고,"
        f"공정온도-대기온도 차이는 {fact['temp_diff']:.2f}K이고, "
        f"규칙 계산 결과 고장 조건 (공정온도 - 대기온도) < 8.6K AND 회전속도 < 1380rpm 해당 여부는 {fact['triggered']}야. "
        "이 정보를 바탕으로 고장 여부, 확신도, 근거를 판단해."
    )

    verdict: ExpertVerdict = llm.invoke(prompt)

    result = build_expert_result("HDF", state, fact, verdict)

    return {"expert_results": {"HDF": result}}


# --------------------------------------------------------------------------------------------------------------


def pwf_expert_node(state: DiagnosisState) -> dict:
    torque = state["torque"]
    rotational_speed = state["rotational_speed"]

    fact = check_pwf(torque, rotational_speed)

    prompt = (
        "너는 설비 동력고장(PWF) 진단 전문가야. "
        f"토크는 {torque}Nm이고, "
        f"회전속도는 {rotational_speed}rpm이고,"
        f"동력은 {fact['power']}W이고, "
        f"규칙 계산 결과 고장 조건 '동력이 3500W 미만 OR 동력이 9000W 초과' 해당 여부는 {fact['triggered']}야. "
        "이 정보를 바탕으로 고장 여부, 확신도, 근거를 판단해."
    )

    verdict: ExpertVerdict = llm.invoke(prompt)

    result = build_expert_result("PWF", state, fact, verdict)

    return {"expert_results": {"PWF": result}}


# --------------------------------------------------------------------------------------------------------------


def osf_expert_node(state: DiagnosisState) -> dict:
    tool_wear_time = state["tool_wear_time"]
    torque = state["torque"]
    product_type = state["type"]  # 내장함수 type()과 이름 겹치는 걸 피하려고 개명

    fact = check_osf(tool_wear_time, torque, product_type)

    prompt = (
        "너는 설비 과응력고장(OSF) 진단 전문가야. "
        f"공구 누적 사용 시간은 {tool_wear_time}min이고, "
        f"토크는 {torque}Nm이고, "
        f"제품 등급은 {product_type}이고, "
        f"공구마모시간×토크로 계산한 응력은 {fact['strain']:.1f}이고, "
        f"제품 등급 {product_type}의 임계치는 {fact['threshold']}이고, "
        f"규칙 계산 결과 응력이 임계치를 초과하는지 여부는 {fact['triggered']}야. "
        "이 정보를 바탕으로 고장 여부, 확신도, 근거를 판단해."
    )

    verdict: ExpertVerdict = llm.invoke(prompt)

    result = build_expert_result("OSF", state, fact, verdict)

    return {"expert_results": {"OSF": result}}


# --------------------------------------------------------------------------------------------------------------


def verifier_node(state: DiagnosisState) -> dict:
    expert_results = state["expert_results"]  # 1. 4명(또는 그중 완료된) 결과를 통째로 읽음

    # 2. 확신도 내림차순 정렬. 정렬 자체는 그냥 파이썬 로직이라 LLM한테 안 시킴
    sorted_results = sorted(
        expert_results.items(), key=lambda item: item[1]["confidence_score"], reverse=True
    )

    lines = []
    for failure_type, result in sorted_results:
        if result["unresolved"]:  # 3. 재시도 2회 넘게 실패한 전문가는 판정 불가로 그대로 보고
            lines.append(f"- {failure_type}: 판정 불가 (사유: {result['unresolved_reason']})")
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

    overall_assessment = text_llm.invoke(prompt).content  # 5. 자연어 총평 생성 (구조화 출력 아님)

    return {"overall_assessment": overall_assessment}  # 6. 바뀐 필드만 반환


if __name__ == "__main__":
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

    # 아직 그래프로 안 묶었으니 4개 노드를 수동으로 순서대로 호출해서 State를 직접 합쳐봄
    state = dict(sample_state)
    for node in (twf_expert_node, hdf_expert_node, pwf_expert_node, osf_expert_node):
        update = node(state)
        state["expert_results"] = {**state["expert_results"], **update["expert_results"]}

    print(verifier_node(state)["overall_assessment"])
