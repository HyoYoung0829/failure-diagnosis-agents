import asyncio
import csv
import json
import random
from pathlib import Path

from failure_diagnosis_agents.graph import graph

DATA_PATH = Path(__file__).parent.parent.parent / "data" / "ai4i2020.csv"
REPORT_PATH = Path(__file__).parent.parent.parent / "docs" / "evaluation.md"

FAILURE_TYPES = ["TWF", "HDF", "PWF", "OSF"]


def build_sample(per_type: int = 10, normal: int = 20, seed: int = 7) -> list[dict]:
    rows = list(csv.DictReader(open(DATA_PATH, encoding="utf-8-sig")))
    random.seed(seed)

    picked, seen = [], set()
    for col in FAILURE_TYPES:
        pool = [r for r in rows if r[col] == "1"]
        for r in random.sample(pool, min(per_type, len(pool))):
            if r["UDI"] not in seen:
                picked.append(r)
                seen.add(r["UDI"])

    normal_pool = [r for r in rows if r["Machine failure"] == "0"]
    for r in random.sample(normal_pool, normal):
        if r["UDI"] not in seen:
            picked.append(r)
            seen.add(r["UDI"])

    return picked


def row_to_state(r: dict) -> dict:
    return {
        "case_id": int(r["UDI"]),
        "type": r["Type"],
        "air_temperature": float(r["Air temperature [K]"]),
        "process_temperature": float(r["Process temperature [K]"]),
        "rotational_speed": float(r["Rotational speed [rpm]"]),
        "torque": float(r["Torque [Nm]"]),
        "tool_wear_time": float(r["Tool wear [min]"]),
        "expert_results": {},
        "overall_assessment": None,
    }


async def run_case(r: dict) -> dict:
    state = row_to_state(r)
    result = await graph.ainvoke(state)

    row_result = {"case_id": int(r["UDI"]), "predictions": {}, "actuals": {}}
    for ft in FAILURE_TYPES:
        expert = result["expert_results"].get(ft, {})
        row_result["predictions"][ft] = expert.get("is_failure")
        row_result["actuals"][ft] = r[ft] == "1"
        if expert.get("unresolved"):
            row_result.setdefault("unresolved", []).append(ft)
    return row_result


async def main() -> None:
    sample = build_sample()
    print(f"{len(sample)}건 평가 시작...")

    results = []
    for i, r in enumerate(sample, 1):
        res = await run_case(r)
        results.append(res)
        print(f"  [{i}/{len(sample)}] case {res['case_id']} done")

    # 집계: 원인별 confusion matrix
    stats = {ft: {"tp": 0, "fp": 0, "tn": 0, "fn": 0} for ft in FAILURE_TYPES}
    mismatches = []
    for res in results:
        for ft in FAILURE_TYPES:
            pred, actual = res["predictions"][ft], res["actuals"][ft]
            if pred is None:  # unresolved
                continue
            if pred and actual:
                stats[ft]["tp"] += 1
            elif pred and not actual:
                stats[ft]["fp"] += 1
                mismatches.append((res["case_id"], ft, pred, actual))
            elif not pred and actual:
                stats[ft]["fn"] += 1
                mismatches.append((res["case_id"], ft, pred, actual))
            else:
                stats[ft]["tn"] += 1

    lines = ["# 평가 결과 (Evaluation)\n", f"샘플 {len(sample)}건 (원인별 10건 + 정상 20건) 기준.\n"]
    lines.append("## 원인별 정확도\n")
    lines.append("| 원인 | 정확도 | TP | FP | TN | FN |")
    lines.append("|---|---|---|---|---|---|")
    for ft in FAILURE_TYPES:
        s = stats[ft]
        total = sum(s.values())
        acc = (s["tp"] + s["tn"]) / total if total else 0.0
        lines.append(f"| {ft} | {acc:.1%} | {s['tp']} | {s['fp']} | {s['tn']} | {s['fn']} |")

    lines.append("\n## 틀린 케이스\n")
    if mismatches:
        lines.append("| case_id | 원인 | 예측 | 실제 |")
        lines.append("|---|---|---|---|")
        for case_id, ft, pred, actual in mismatches:
            lines.append(f"| {case_id} | {ft} | {pred} | {actual} |")
    else:
        lines.append("없음 — 전부 일치")

    unresolved_cases = [(res["case_id"], res["unresolved"]) for res in results if res.get("unresolved")]
    lines.append("\n## 판정 불가(unresolved)\n")
    if unresolved_cases:
        for case_id, types in unresolved_cases:
            lines.append(f"- case {case_id}: {', '.join(types)}")
    else:
        lines.append("없음")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n보고서 저장: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
