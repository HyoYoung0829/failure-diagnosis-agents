# 로드맵 (Roadmap)

DB 설계 순서(요구사항 → 엔티티 → 스키마 → CRUD → 트랜잭션)에 대응시켜서 체계적으로 진행.
각 단계는 이전 단계가 끝나야 의미가 있음 — 순서 건너뛰지 말 것.

## 0. 준비 (Setup) — 완료

- [x] 레포 생성, `uv` 프로젝트 초기화
- [x] AI4I 2020 데이터셋 다운로드 (`data/ai4i2020.csv`)
- [x] 데이터셋 가이드 문서 작성 (`data/README.md`)
- [x] 의존성 설치 (`langgraph`, `langchain-openai`, `pandas`, `python-dotenv`)
- [x] API 키 설정 (`.env`)

## 1. 역할(에이전트) 식별 — DB의 "엔티티 식별"에 해당

**구조 결정: mixture-of-experts (전문가 합의) 패턴**
단일 진단 에이전트 대신, 고장 유형별 전문가 에이전트 여러 개가 각자 독립적으로 의견을 내고,
검증 에이전트가 이를 종합·중재한다.

- [x] 전문가 에이전트 목록 확정 — 4명: TWF 전문가 / HDF 전문가 / PWF 전문가 / OSF 전문가 (RNF는 패턴 없어서 제외)
- [x] 각 전문가 에이전트의 책임 범위 정의
  - TWF 전문가: 입력=공구마모시간
  - HDF 전문가: 입력=대기온도, 공정온도, 회전속도
  - PWF 전문가: 입력=토크, 회전속도
  - OSF 전문가: 입력=토크, 공구마모시간, Type
  - 공통 출력: 원인 판정(예/아니오) + 확신도(confidence) + 근거(reasoning)
- [x] 검증 에이전트(Verifier Agent)의 책임 범위 정의
  - 4명의 판정(예/아니오 + 확신도 + 근거)을 다수결로 강제 통합하지 않음 — 실제 데이터에도 원인 2개 이상 동시 발생 24건 있음, 여러 원인 동시 성립 가능함을 그대로 인정
  - 확신도 높은 순으로 정렬해서 출력
  - 각 전문가 판정은 **MCP 툴이 계산한 규칙 결과**와 대조해서 검증 (CSV 라벨 컬럼은 사용 안 함 — 라벨은 배포 환경에 없는 값이라 8단계 최종 평가에서만 사용)
- [x] 상충 처리 방침: "상충"을 억지로 하나로 합치치 않고, 각자 독립적으로 판정 인정. 대신 MCP 툴 계산과 다른 경우만 "불일치"로 취급해 재시도 트리거
- [x] 전문가 에이전트들 + 검증 에이전트가 State를 통해 어떻게 주고받는지 흐름
  1. 사용자가 사건(행) 하나를 던짐 → State에 사건번호(UDI) + 센서값 6개 파싱
  2. 전문가 4명이 각자 필요한 센서값만 보고, MCP 툴 호출해서 규칙 계산 사실을 받아옴
  3. 그 사실을 참고해 전문가가 판정(고장 유무 + 확신도 + 근거) 생성
  4. 검증(부모) 노드가 각 전문가 판정 vs MCP 계산 사실을 재대조 → 불일치면 해당 전문가에게 피드백과 함께 재시도 지시 (최대 2회)
  5. 2회 넘게 불일치 지속 시 해당 전문가는 "판정 불가 + 사유"로 보고, 부모 노드는 성공한 전문가 결과는 확신도순 정렬해 정상 출력, 실패한 전문가는 감추지 않고 그대로 노출 (graceful degradation)
  6. (별도) MCP 툴 호출 자체가 실패하는 경우는 지수백오프로 최대 2회 재시도 — 이건 추론 재검증 루프와는 별개의 인프라 레벨 재시도

## 2. State 스키마 설계 — DB의 "테이블 스키마 + 정규화"에 해당

- [x] 입력 데이터 필드 정의: `case_id`(UDI), `type`(L/M/H, product_id 대신 파싱된 값 저장), 센서값 6개
- [x] 전문가별 출력 필드 정의: `dict[FailureType, ExpertResult]` — `is_failure(bool|None)`, `confidence_score`, `reason`, `mcp_fact`, `retry_count`, `unresolved`, `unresolved_reason`
- [x] 검증 에이전트 출력 필드 정의: `overall_assessment`(str) — 정렬된 표는 `expert_results`를 그대로 정렬해서 보여주면 되므로 별도 필드 불필요
- [x] 루프 제어 필드 정의: 전문가별 `retry_count`를 `ExpertResult` 안에 내장 (지역변수 불가 — LangGraph는 State만 노드 호출 간에 유지됨)
- [x] `TypedDict`로 State 클래스 작성 → [state.py](../src/failure_diagnosis_agents/state.py)
- [x] 필드마다 "이 필드는 어느 노드가 쓰고 어느 노드가 읽는가" 표로 정리
  - TWF 전문가: 읽기=`tool_wear_time` / 쓰기=`expert_results["TWF"]`
  - HDF 전문가: 읽기=`air_temperature, process_temperature, rotational_speed` / 쓰기=`expert_results["HDF"]`
  - PWF 전문가: 읽기=`torque, rotational_speed` / 쓰기=`expert_results["PWF"]`
  - OSF 전문가: 읽기=`tool_wear_time, torque, type` / 쓰기=`expert_results["OSF"]`
  - 검증(부모) 노드: 읽기=`expert_results` 전체 / 쓰기=`overall_assessment`
  - 조건부 엣지(라우팅): State는 읽기만, 쓰기 없음 (다음 노드 결정만)

## 3. 정답 규칙 함수 (Ground-truth Rule Functions) — 가드레일의 재료

- [x] TWF/HDF/PWF/OSF 판별 함수 각각 순수 함수로 작성 → [rules.py](../src/failure_diagnosis_agents/rules.py)
  - 공통 반환: `{"triggered": bool, ...계산 중간값}` — TWF의 `triggered`는 "확정 고장"이 아니라 "고장 가능 구간(200~240분)"이라는 점 주의 (무작위 트리거라 결정론적으로 확정 불가)
- [x] 함수 단위 테스트 — CSV 실제 행(UDI 3237/51/70/1)으로 HDF·PWF·OSF·정상 케이스 검증, `demo()`/`__main__`으로 실행
- [x] RNF는 예측 불가 노이즈로 취급 — 전문가 자체를 안 만들기로 결정 (1단계에서 이미 확정)

## 4. 노드 구현 — DB의 "CRUD 정의"에 해당

- [x] 전문가 노드 4개 완성 → [nodes.py](../src/failure_diagnosis_agents/nodes.py) (`twf_expert_node`, `hdf_expert_node`, `pwf_expert_node`, `osf_expert_node`)
  - 공통 패턴: State에서 입력 꺼내기 → 규칙 함수로 fact 계산 → fact의 중간값까지 프롬프트에 포함 → `ExpertVerdict` 구조화 출력 → `ExpertResult` 조립 → `{"expert_results": {"XXX": result}}` 반환
  - (수정 완료) `osf_expert_node`의 변수명 `type` → `product_type`으로 개명 (내장함수명 겹침 방지)
- [x] 검증 노드(`verifier_node`) 완성 → [nodes.py](../src/failure_diagnosis_agents/nodes.py)
  - 확신도 내림차순 정렬 → 전문가별 판정 vs `mcp_fact['triggered']` 대조 (TWF는 특수취급: "구간 밖인데 고장"만 불일치, "구간 안인데 정상"은 정상 판단으로 인정) → 계산된 사실을 LLM에 주고 총평 문장만 생성
  - 4개 노드 + 검증 노드를 수동으로 이어붙여 실제 LLM 호출로 end-to-end 확인 완료
  - 버그 발견/수정: `python-dotenv` 설치만 해두고 `load_dotenv()` 호출이 없어서 `.env`의 API 키를 못 읽던 문제 → `nodes.py` 상단에 추가
- [x] (선택) 컨텍스트 엔지니어링: 전문가마다 필요한 센서값만 골라 State에서 꺼내고, 규칙함수가 계산한 중간값(temp_diff/power/strain 등)도 프롬프트에 포함해 LLM이 재계산 안 하게 구성 완료

## 5. 루프 & 라우팅 — DB의 "트랜잭션/조인 로직"에 해당

- [x] 조건부 엣지: `routing_function`이 `expert_results`를 순회하며 불일치(`is_mismatch`)한 전문가만 노드 이름 리스트로 리턴 → `add_conditional_edges`로 등록 → [graph.py](../src/failure_diagnosis_agents/graph.py)
- [x] 재시도 횟수 제한: 전문가별 최대 2회 — `build_expert_result`가 이전 시도의 `retry_count`를 이어받아 누적 (처음엔 하드코딩 0이라 무한루프 위험 있었던 버그 수정)
- [x] escalate 방침: 2회 초과 시 그 전문가만 `unresolved=True` + 사유로 최종 보고, 나머지 성공한 전문가 결과는 그대로 살려서 출력 (부분 실패 허용, 전체 재시도 아님)
- [x] `StateGraph` 조립 + 팬아웃(START→4전문가)/팬인(4전문가→verifier) + `compile()`, 실제 실행으로 정상 케이스 end-to-end 확인 완료

## 6. MCP 도구 연동

- [x] `rules.py`의 4개 함수를 `@mcp.tool()`로 감싼 MCP 서버 작성 (stdio transport) → [mcp_server.py](../src/failure_diagnosis_agents/mcp_server.py)
- [x] `MultiServerMCPClient`로 연결 테스트 (`get_tools()`, 툴 1개 직접 호출) → [mcp_client_test.py](../src/failure_diagnosis_agents/mcp_client_test.py)
- [x] 전문가 4개 노드를 전부 "LLM이 직접 MCP 툴을 호출"하는 구조로 전환 → 공통 로직은 `run_expert_via_mcp()` 헬퍼 하나로 묶음(중복 제거)
  - 패턴: 사실을 프롬프트에 미리 박아넣지 않고, LLM이 툴 호출 요청(`tool_calls`) → 우리가 대신 실행 → 결과를 대화에 넣고 최종 구조화 판정 받기 (2단계 LLM 호출)
  - 노드가 전부 `async def`로 바뀜 — LangGraph dev(ASGI 서버)에서 `asyncio.run()`을 노드 안에 중첩 호출하면 블로킹 감지기(`blockbuster`)가 에러 던지는 버그 발견/수정 (노드를 네이티브 async로, `asyncio.run()` 제거)
  - 부수 변경: 그래프에 async 노드가 생겨서 `.invoke()` 대신 `.ainvoke()` 사용 필요
- [x] 실제 그래프 전체(`graph.ainvoke`)로 end-to-end 확인, 실제 라벨과 일치 재확인

## 7. 그래프 조립 & 시각화

- [x] `StateGraph` 빌드, 노드/엣지 연결, `compile()` → [graph.py](../src/failure_diagnosis_agents/graph.py)
- [x] `langgraph dev`로 LangGraph Studio에서 그래프 구조 확인 (`langgraph.json` + `.claude/launch.json` 설정)
- [x] 실제 데이터셋 케이스(UDI 70, 정답=PWF+OSF 동시 발생)로 실행 → 우리 그래프도 PWF/OSF만 고확신도(0.95)로 정확히 짚어냄, mixture-of-experts 설계가 다중 원인 케이스에서 실제로 작동함을 확인
- [x] 루프(재시도)가 의도대로 도는지 확인 — temperature=0 LLM이 주어진 fact를 그대로 따라가서 자연스러운 입력으론 불일치가 안 생김(오히려 설계가 잘 됐다는 증거). 그래서 `routing_function`을 LLM 호출 없이 가짜 State로 직접 단위 테스트: (1)특정 전문가만 불일치→그 노드만 재시도 대상 (2)전부 일치→END (3)이미 unresolved인 전문가는 재시도 제외하고 END, 3케이스 모두 통과

## 8. 평가 (Evaluation)

- [x] 층화추출 샘플(원인별 10건 + 정상 20건 = 60건)로 평가 → [evaluate.py](../src/failure_diagnosis_agents/evaluate.py)
- [x] 원인별 정확도 집계 → [docs/evaluation.md](evaluation.md): HDF/PWF/OSF 100%, TWF 83.3%
- [x] 실패 사례 분석: TWF 오차는 데이터 자체의 확률적 생성 규칙(200~240분 구간 내 무작위 발생)에 기인한 구조적 한계로, 시스템/루프 결함 아님. 재시도 루프는 이번 실행에서 trigger 안 됨(unresolved 없음) — 전문가가 MCP 사실과 매번 일치하는 판정을 냈다는 뜻

## 9. (선택) 최소 데모

- [ ] Streamlit/Gradio로 센서값 입력 → 진단 결과 확인하는 최소 UI (핵심 완성 후에만)
