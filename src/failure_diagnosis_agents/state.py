from typing import Annotated, Literal, TypedDict

FailureType = Literal["TWF", "HDF", "PWF", "OSF"]


class ExpertResult(TypedDict):
    is_failure: bool | None  # 고장 유무
    confidence_score: float  # 확신도 점수
    reason: str  # 이렇게 판정한 이유
    mcp_fact: dict  # 정답 값
    retry_count: int  # 재시도 횟수 (그래프에서는 상태로 선언해야 재시도 카운트가 가능)
    unresolved: bool  # 검증 실패 여부 (2회 재시도 후에도 판정 불가 (unresolved))
    unresolved_reason: str | None  # 검증 왜 실패 했는지 이유


def merge_expert_results(
    existing: dict[FailureType, ExpertResult], update: dict[FailureType, ExpertResult]
) -> dict[FailureType, ExpertResult]:
    # 병렬로 도는 전문가 노드들의 부분 업데이트를 합침. 같은 key로 재시도 오면 통째로 교체.
    return {**existing, **update}


# 진단 상태
class DiagnosisState(TypedDict):
    case_id: int  # 사건 번호
    type: Literal["L", "M", "H"]  # 제품 타입
    air_temperature: float  # 대기 온도
    process_temperature: float  # 공정 온도
    rotational_speed: float  # 회전 속도
    torque: float  # 토크
    tool_wear_time: float  # 공구 누적 사용 시간

    expert_results: Annotated[
        dict[FailureType, ExpertResult], merge_expert_results
    ]  # 각 전문가들의 결과

    overall_assessment: str | None  # 총평


def demo() -> None:
    a: dict[FailureType, ExpertResult] = {
        "TWF": {
            "is_failure": False,
            "confidence_score": 0.9,
            "reason": "tool wear 50min, 200~240min 구간 아님",
            "mcp_fact": {"tool_wear_time": 50},
            "retry_count": 0,
            "unresolved": False,
            "unresolved_reason": None,
        }
    }
    b: dict[FailureType, ExpertResult] = {
        "HDF": {
            "is_failure": True,
            "confidence_score": 0.8,
            "reason": "온도차 5K, 회전속도 1200rpm 모두 임계치 미달",
            "mcp_fact": {"temp_diff": 5.0, "rotational_speed": 1200},
            "retry_count": 1,
            "unresolved": False,
            "unresolved_reason": None,
        }
    }

    # 서로 다른 전문가의 병렬 결과가 합쳐지는지 확인
    merged = merge_expert_results(a, b)
    assert set(merged.keys()) == {"TWF", "HDF"}

    # 같은 전문가(HDF)가 재시도해서 값이 교체되는지 확인, 다른 전문가(TWF)는 안 건드려지는지 확인
    retry_b: dict[FailureType, ExpertResult] = {
        "HDF": {**b["HDF"], "retry_count": 2, "confidence_score": 0.95}
    }
    merged2 = merge_expert_results(merged, retry_b)
    assert merged2["HDF"]["retry_count"] == 2
    assert merged2["TWF"]["confidence_score"] == 0.9

    print("state.py self-check passed")


if __name__ == "__main__":
    demo()
