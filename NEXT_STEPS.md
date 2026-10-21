# NEXT_STEPS — 다른 노트북에서 이어서 작업하기 위한 계획서

> 이 문서는 작업 이어받기용이다. 제출 전에 삭제하거나 `doc/`로 옮겨도 된다.
> 작성 시점 기준: 단위 테스트 30개 통과, 모듈화 진행 중(노드 4개 분리 완료).
> 설계·진행 상태의 정리본은 Notion 페이지 "AI Agent Mini-Project"
> (https://app.notion.com/p/3ffed6bd74128097819ccd63a68df2e2)에도 있다.
> 실측 결과와 작업 기록의 원본은 `doc/REPORT_LOG.md`.

---

## 0. 이 프로젝트가 무엇인가

운영 인시던트 대응 에이전트(`all_total_vue`)를 개선하는 과제 1번(기존 Base AI Agent 개선).
- 일정: 결과 보고서와 Git 주소 제출은 Day3 13시, 발표는 Day3 17:30(1인 5분, 준비 포함 최대 6분).
- 평가: 기능 구현 완성도 30, 기술 요소 30, 한계·트레이드오프 20, 발표 20, Before/After 수치 보너스 10.
- **필수 기술 요소 7개**: Multi-Agent, MCP, RAG, 의존성 주입, LangSmith, 모듈화, 단위 테스트.

### 지금까지 한 개선
1. **RAG**: runbook 선택을 키워드 규칙에서 임베딩 의미 검색(bge-m3)으로 교체. 검색어는 질문에 아는 시스템이 있을 때만 알림을 함께 쓰는 `auto` 방식(23문항 기준 규칙 57% → 83%).
2. **모르는 시스템 안내**: 목록에 없는 시스템이면 다른 시스템으로 대체 조회하지 않고 "조회 불가"를 안내(`unknown_system_node`).
3. **route 오분류 보정**: 작은 모델이 장애 질문을 잡담으로 분류해도 시스템 이름이 있으면 장애로 바로잡음.
4. **매뉴얼 없음 안내**: 유사도가 임계값 미만이면 답변 끝에 알림 문구 추가.
5. **평가 도구** `eval/`, **단위 테스트** `tests/`(30개).

---

## 1. 새 노트북 환경 준비 (순서대로)

```bash
# 1) 받기
git clone https://github.com/seokyoung0318/Ops-Chat.git
cd Ops-Chat

# 2) 파이썬 가상환경 (이 폴더 안에만 설치됨)
bash sh/setup_venv.sh

# 3) Ollama 설치 후 모델 3개 받기 (용량: qwen3:8b 약 5.2GB, bge-m3 약 1.2GB, qwen3:0.6b 약 0.5GB)
ollama pull qwen3:0.6b
ollama pull qwen3:8b
ollama pull bge-m3

# 4) 설정 파일 만들기 (.env 는 git 에 올라가지 않음)
cp .env.example .env     # 열어서 본인 키로 채운다. LangSmith를 안 쓰면 LANGCHAIN_TRACING_V2=false
```

환경이 맞는지 확인:
```bash
.venv/bin/python -m pytest tests -q            # 30 passed 가 나와야 함
.venv/bin/python -c "import agent.graph as g; from types import SimpleNamespace; g.build_graph(SimpleNamespace(version='v2')); print('build_graph OK')"
```

실행(터미널 3개): 백엔드 `bash sh/run_agent_ollma.sh`, 프론트 `bash sh/run_frontend.sh`, 작업용. 브라우저 http://localhost:8600.
- 기존 키워드 규칙(Before)으로 켜기: `CLASSIFIER=rules bash sh/run_agent_ollma.sh`

---

## 2. 현재 상태

### 모듈화 진행 (동작은 바꾸지 않고 옮기기만 한다)
| 파일 | 내용 | 상태 |
|---|---|---|
| `agent/systems.py` | 시스템 목록과 이름 추출(`KNOWN_SYSTEMS`, `_mentioned_systems`, `_split_systems`, `_extract_system_name`) | 완료 |
| `agent/state.py` | `AgentState`, `_cost` | 완료 |
| `agent/nodes/routing.py` | route, chat_answer, unknown_system, `_after_route` | 완료 |
| `agent/nodes/planning.py` | plan, gate | 완료 |
| `agent/nodes/research.py` | research | 완료 |
| `agent/nodes/replan.py` | replan_check, `RAG_INPUT`, `_search_text`, `_classify_incident_type`, `_after_replan_check` | **코드 이동 완료, 단 아래 "1순위 함정" 확인 필요** |
| `agent/nodes/analysis.py` | analysis_node | **빈 파일, 아직 안 옮김** |
| `agent/nodes/writing.py` | write_node, validate_node, finalize_node, `_after_validate` | **빈 파일, 아직 안 옮김** |
| `agent/graph.py` | 마지막에는 `build_graph`(노드 연결)만 남긴다 | 진행 중 |

### 1순위 함정: `eval/run_eval.py`가 조용히 틀린 결과를 낼 수 있다
`RAG_INPUT`과 `_search_text`가 `replan.py`로 옮겨졌는데, 평가 스크립트는 아직 `graph.RAG_INPUT = ...`으로 방식을 바꾼다. 이 줄은 **에러 없이** `graph`에 새 속성만 만들 뿐 `replan.py`의 값은 안 바뀌므로, 세 RAG 방식이 모두 기본값(`auto`)으로만 돌아 **방식별 결과가 같게 나온다.**
- 고치기: `eval/run_eval.py`에서 `from agent.nodes import replan`을 추가하고 `graph.RAG_INPUT = RAG_INPUT_OF[m]`을 `replan.RAG_INPUT = RAG_INPUT_OF[m]`으로 바꾼다.
- 검증(반드시): 고친 뒤 `.venv/bin/python eval/run_eval.py`(Ollama 필요, 약 1.5분)를 돌려 아래 기준값과 같은지 확인.

| 평가 세트 | rules | rag_query | rag_alerts | rag_auto |
|---|---|---|---|---|
| `eval/queries.json` (23문항) | 13/23 | 17/23 | 14/23 | 19/23 |
| `eval/queries_heldout.json` (20문항, `.venv/bin/python eval/run_eval.py eval/queries_heldout.json`) | 10/20 | 15/20 | 10/20 | 17/20 |

(LLM 출력이 매번 달라도 이 평가는 runbook 선택만 보므로 값이 같아야 한다. 방식별 값이 서로 같게 나오면 위 함정이다.)

### 이미 확인된 것
- 테스트 30개 통과(`tests/test_systems.py` 6, `test_routing.py` 7, `test_rag.py` 7, `test_nodes.py` 10).
- 그래프 조립 시험 통과. 이 시험은 단위 테스트가 못 잡은 실제 버그(`_after_replan_check` 가져오기 누락)를 잡았다 → **그래프 전체 통합 테스트가 필요**하다(아래 3번).

---

## 3. 남은 작업 (우선순위 순)

작업 방식(매번 같은 4단계): ① 새 파일에 코드를 붙여넣고 단독 확인 → ② `graph.py`에서 같은 코드를 지우고 `from .nodes.xxx import ...` 추가 → ③ 같은 객체인지(`g.x is r.x`)와 `pytest` 확인 → ④ commit.

### A. 모듈화 마무리 (약 1시간)
1. `eval/run_eval.py` 수정과 기준값 검증 (위 "1순위 함정").
2. `analysis.py`로 `analysis_node` 이동.
3. `writing.py`로 `write_node`, `validate_node`, `finalize_node`, `_after_validate` 이동.
4. `graph.py`에는 `build_graph`만 남기고, 안 쓰게 된 import 정리. 단 테스트가 `agent.graph`에서 가져오는 이름(`_mentioned_systems`, `_split_systems`, `finalize_node` 등)은 테스트의 import를 새 위치로 바꾼 뒤에만 지운다.
5. 주의: 이동하면 `RAG_INPUT`처럼 모듈 안의 값을 바꾸는 코드(테스트, 평가)는 새 위치를 가리켜야 한다.
6. 확인용 명령 (이동 후): `.venv/bin/python -m pytest tests -q`와 build_graph 시험, 그리고 평가 기준값.

### B. 하드코딩 정리 (약 1시간, 방식 결정 필요)
| # | 하드코딩 | 위치 | 방향 |
|---|---|---|---|
| 1 | 데이터 파일을 못 읽으면 `{"auth-service","web-01"}` | `systems.py`, `ollama_llm.py`, `openai_llm.py`에 복사됨 | `systems.py` 한 곳으로 통일, 읽기 실패 시 경고 출력 |
| 2–4 | 시스템 이름이 없으면 `auth-service`를 기본 조회 | `systems.py`의 `_extract_system_name`, `ollama_llm.py`의 `_guess_target`·`_guess_targets`·plan 프롬프트 | 결정 필요: **A(추천)** 기본값을 설정값 `DEFAULT_SYSTEM`으로 빼고 쓰였을 때 답변에 표시, B 기본 조회 없이 질문만으로 검색, C 되묻기 |
| 5 | 키워드 규칙과 `db-down` 기본값 | `replan.py` | Before 비교용으로 보존, 보존용임을 주석에 명시 |
| 7 | 검수 기준 "30자 이상 + `1)` 포함" | `validate_node` | 수치 인용 검사 추가(평가 보강과 함께) |

### C. MCP 로그 Tool 추가 (약 1시간)
- `mcp_server.py`에 `@mcp.tool()`로 `get_recent_logs(system_name)` 추가(같은 `ops` 서버에 추가, 새 서버 아님).
- 가짜 로그 데이터 `data/logs/`(시스템별 JSON 또는 텍스트) 작성. **발표에서 "가짜 샘플 데이터"라고 밝힐 것.**
- 답변 작성 단계가 로그를 인용하도록 `ollama_llm.py`, `openai_llm.py`, `fake_llm.py`의 근거 정리(`write` 안의 facts 만드는 부분, `c["source"] == "runbook"` 처리하는 곳 근처)에 `logs` 출처 처리 추가.

### D. 멀티 에이전트 (약 3–4시간)
- 구조: `research_supervisor`가 서브 에이전트(LangGraph 서브그래프)를 호출.
  - `metrics_agent`(MCP Tool로 상태·알림 조회)와 `log_agent`(MCP Tool로 로그 조회)를 **동시에** 실행.
  - `runbook_agent`는 metrics의 알림을 받은 뒤 RAG로 runbook을 골라 MCP Resource로 읽는다. → `replan_check` 재조사 반복이 사라져 `replan_rounds` 1 → 0.
- `PIPELINE=single|multi` 환경변수로 기존 방식과 전환(`CLASSIFIER` 스위치와 같은 방식).
- 서브 에이전트의 진행은 총괄 노드가 이벤트 목록으로 모아 내보낸다(서브그래프 스트리밍 설정은 쓰지 않음 → 화면과 `server.py` 변경 최소).
- 파일: `agent/agents/`(metrics_agent, log_agent, runbook_agent, research_supervisor).
- 측정: 기존 방식과 runbook 선택 정확도 동일성(회귀 없음), `replan_rounds`, 서브 에이전트별 시간.

### E. 단위 테스트 보강
- `tests/test_agents.py`: 서브 에이전트별(가짜 MCP, 가짜 검색기).
- `tests/test_graph_integration.py`: **그래프 전체를 가짜 `deps`로 끝까지 실행**(가짜 LLM·MCP·검색기). `build_graph` 호출 자체를 포함해야 한다.
- 새 테스트마다 이름은 영어(`test_...`), 한글 주석으로 무엇을 검사하는지 적는다.

### F. LangSmith 증거 (약 1시간)
- `.env`에서 `LANGCHAIN_TRACING_V2=true`이면 `@traceable` 노드가 이미 기록된다.
- 서브 에이전트별 이름을 붙이고 선택된 runbook, 점수, `select_ms`를 메타데이터로 남긴다.
- 증거: 한 요청의 트레이스 트리 캡처(총괄 → 서브 에이전트 → MCP 호출).
- 선택: 평가 질문을 LangSmith 데이터셋으로 올려 방식별 실험 비교. **데이터가 외부로 전송되므로 하기 전에 본인 확인을 받을 것.**

### G. 마무리 (약 3시간)
- **새 질문 세트를 한 번 더 만들어 최종 평가를 1회만 실행** (기존 43문항은 결과를 본 개발용이라 과적합 위험. 새 세트에는 범위 밖 질문을 더 많이 넣을 것).
- Human-in-the-loop, 메모리 요약은 **설계안만** 작성(구현 안 함).
- 슬라이드(발표 5분 기준 본문 7–8장), 한계와 트레이드오프 정리(Notion에 초안 있음).
- 제출물: `.env.example`에 실제 키가 없는지 확인(현재 견본 파일은 자리표시자), `NEXT_STEPS.md` 정리, GitHub 주소와 결과 보고서 주소 등록.

시간이 부족하면 줄이는 순서: G의 약점 수정, F의 데이터셋 실험, B의 일부. **A, C, D, E, F의 트레이스 캡처는 지킨다.**

---

## 4. 이미 내린 결정과 알려진 한계

### 결정
- 남은 약점(gateway-service 타임아웃·504 질문 2건 오답, 모호한 구어체, 임계값 취약)은 **한계로 두고** 필수 요소를 끝낸 뒤 시간이 남을 때 본다.
- 멀티 에이전트는 설계안이 아니라 **구현**한다.
- RAG는 현재 `replan_check`에서 실행한다. 이유: 검색에 알림(상태 조회 결과)을 쓰면 정확도가 오르기 때문(질문만 74% vs `auto` 83%). 멀티 에이전트 단계에서 `runbook_agent`로 옮겨 상태 조회 직후에 검색한다(재조사 반복 제거).
- 모듈화 중에는 동작을 바꾸지 않는다. 하드코딩 정리는 모듈화 직후에 한다.

### 알려진 한계 (보고서·발표에 정직하게)
- `auto` 방식과 83%는 같은 질문으로 설계해 과적합 위험이 있다(검증용 20문항에서 80→85%로 순위는 유지, 같은 작성자·소표본).
- 임계값 0.5는 임시값에서 출발했고 0.50–0.70 구간만 시험했다. 범위 밖 질문(최대 0.509)과 정답 질문(최소 0.528) 사이 틈이 매우 좁다.
- 시스템 이름은 `xxx-service`, `xxx-숫자` 형식만 인식한다(한글 표현은 못 잡음).
- RAG 색인(`rag.py`)과 시스템 목록 읽기는 MCP를 거치지 않고 파일을 직접 읽는다.
- route 분류는 작은 모델(qwen3:0.6b)이라 가끔 틀리고, 시스템 이름이 있으면 설명을 묻는 질문도 장애 경로로 보정된다.
- `cost_usd`는 글자 수로 어림한 추정치이며 실제 과금이 아니다.

---

## 5. 이어서 작업할 때의 규칙 (Claude에게 전달용 맥락)

- 사용자는 **비전공자**이고 코드를 이해하면서 직접 수정하길 원한다. 한 번에 한 단계씩 진행한다.
- 코드나 명령을 줄 때는 묻지 않아도 먼저 **왜 하는지, 무엇을 하는지, 기대 결과**를 최소한의 핵심으로 설명한다.
- 코드는 위치(링크)를 알려 주고 사용자가 직접 붙여넣는 방식이 기본이다. 사용자가 명시적으로 "대신 해줘"라고 한 부분만 직접 수정한다. 사용자에게 알리지 않고 앞서 나가지 않는다.
- 모든 이동·수정 뒤에는 `pytest`와 필요한 확인을 돌리고 저장(commit)한다. 되돌리기는 `git restore 파일`.
- 커밋 메시지와 PR 설명에 **공동 작성자(Co-Authored-By 등) 표시를 넣지 않는다.**
- 파이썬 들여쓰기 실수가 잦았다: 붙여넣은 뒤 앞 공백이 사라지지 않았는지, 저장(탭의 흰 점 사라짐)했는지 먼저 확인한다.
- 설계, 계획, 진행 상태는 Notion 페이지에 적어 사용자가 반복해서 묻지 않게 한다.
- 키(.env)는 절대 저장소에 올리지 않는다. 올리기 전 `git grep -n -E "sk-pro[j]-|lsv2_p[t]_"`로 확인(대괄호 표기는 이 줄 자신이 검사에 걸리지 않게 하려는 것).
- 테스트 함수 이름은 영어, 설명은 한글 주석.
