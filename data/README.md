# AI4I 2020 Predictive Maintenance Dataset

출처(Source): [UCI ML Repository #601](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset)
파일: `ai4i2020.csv` (10,000 rows, synthetic/합성 데이터)

## 컬럼 (Columns)

| 컬럼명 | 설명 | 타입/범위 |
|---|---|---|
| `UDI` | 행 번호 (unique ID), 1~10000 | int, 무의미한 인덱스 |
| `Product ID` | 제품 시리얼 (예: `M14860`), 앞글자가 `Type`과 동일 | string |
| `Type` | 제품 등급 (quality variant) | `L`(low) 60%, `M`(medium) 30%, `H`(high) 10% |
| `Air temperature [K]` | 대기 온도 (Kelvin) | 실측값, 약 295~305K |
| `Process temperature [K]` | 공정 온도 (Kelvin) | 대기온도 + 약 10K, 상관관계 있음 |
| `Rotational speed [rpm]` | 회전 속도 | 동력(power)에서 노이즈 섞어 역산, 약 1150~2900 |
| `Torque [Nm]` | 토크 | 정규분포, 음수 없음, 약 3~77 |
| `Tool wear [min]` | 공구 누적 사용 시간(분) | 제품 등급별로 다르게 누적 (H가 더 오래 버팀) |
| `Machine failure` | **최종 라벨**: 아래 5개 중 하나라도 뜨면 1 | 0/1 |
| `TWF`,`HDF`,`PWF`,`OSF`,`RNF` | 5가지 고장 원인 플래그 (개별적으로 1/0) | 0/1 |

## 고장 원인 5종 — "정답 함수" (Ground-truth rules)

이게 이 데이터셋을 고른 핵심 이유: 아래 규칙이 데이터 생성 논문에 그대로 공개되어 있어서, 에이전트의 진단이 맞았는지 **결정론적으로 검증** 가능함 (LLM 판단에 기댈 필요 없음).

1. **TWF (Tool Wear Failure, 공구마모고장)**
   공구 사용시간이 200~240분 구간에서 무작위로 발생 (해당 구간에서만 발생 가능, 확정적 트리거 아님). 46건.

2. **HDF (Heat Dissipation Failure, 방열고장)**
   `(공정온도 - 대기온도) < 8.6K` **AND** `회전속도 < 1380 rpm` 이면 발생. 115건.

3. **PWF (Power Failure, 동력고장)**
   `동력(W) = 토크(Nm) × 회전속도(rad/s)`. 이 값이 **3500W 미만 또는 9000W 초과**면 발생.
   ⚠️ 회전속도는 rpm 단위이므로 rad/s로 변환 필요: `rad/s = rpm × 2π / 60`. 95건.

4. **OSF (Overstrain Failure, 과응력고장)**
   `공구마모시간(min) × 토크(Nm)`이 제품 등급별 임계치를 초과하면 발생.
   임계치: L=11,000 / M=12,000 / H=13,000 (단위: min·Nm). 98건.

5. **RNF (Random Failure, 무작위고장)**
   패턴 없이 확률적으로 발생 (약 0.1% 확률). 19건. → **예측 불가능한 노이즈**로 취급해야 함 (에이전트가 이걸 맞추려고 하면 안 됨).

## 데이터 확인하며 발견한 주의사항 (Gotchas)

실제로 CSV를 까보니 알아둘 점들:

- **여러 원인이 동시에 발생하는 행이 24건 있음.** 즉 `Machine failure=1`이어도 원인이 하나라고 단정하면 안 됨 — 진단 에이전트가 복수 원인 후보를 낼 수 있어야 함.
- **원인 플래그는 켜졌는데 `Machine failure=0`인 행이 18건 있음.** (예: RNF나 경계값 근처에서 발생) 원 논문 규칙 자체의 노이즈로 보임. 검증 에이전트를 설계할 때 "플래그=1인데 최종 고장은 0"인 케이스를 어떻게 다룰지 미리 정해둘 것.
- **PWF 계산 시 단위 변환을 빼먹기 쉬움** (rpm→rad/s). MCP 툴로 노출할 때 특히 신경 쓸 부분.
- `Product ID`의 첫 글자는 항상 `Type`과 같음 (예: `L47181`은 Type=`L`) — 중복 정보라 피처로 쓸 필요 없음.
- `UDI`, `Product ID`는 진단과 무관한 식별자 — 컨텍스트 엔지니어링 단계에서 프롬프트에 넣지 말 것.

## 이번 프로젝트에서 이 데이터를 쓰는 방식

- **State에 태울 것**: `Air temperature`, `Process temperature`, `Rotational speed`, `Torque`, `Tool wear`, `Type` (원시값 or 요약된 피처)
- **정답 라벨 (평가용, 프롬프트에는 넣지 않음)**: `Machine failure`, `TWF/HDF/PWF/OSF/RNF`
- **가드레일/검증 에이전트**: 위 5개 규칙을 그대로 함수화해서, LLM 진단이 물리적으로 말이 되는지 체크하는 데 사용
- **MCP 툴 후보**: 동력 계산(`torque × rpm→rad/s`), OSF 임계치 비교, HDF 온도차 계산 — LLM이 직접 산수 하지 않고 툴 호출하도록
