# NEXT_STEPS — 다른 노트북에서 이어서 작업하기 위한 계획서

> 이 문서는 작업 이어받기용이다. 제출 전에 삭제하거나 `doc/`로 옮겨도 된다.
> 작성 시점 기준: 단위·통합 테스트 41개 통과, 모듈화·하드코딩 정리·MCP 로그 도구·멀티에이전트(LangGraph 서브그래프) 완료.
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
5. **모듈화**: `graph.py`는 `build_graph`(노드 연결)만 남기고 노드는 `agent/nodes/*`, 시스템 처리는 `agent/systems.py`, 상태는 `agent/state.py`로 분리.
6. **하드코딩 정리**: 기본 시스템을 `agent/systems.py`의 `DEFAULT_SYSTEM`(환경변수로 변경 가능) 한 곳으로 모으고, `ollama_llm.py`·`openai_llm.py`에 복사돼 있던 시스템 처리 코드를 삭제. 데이터 파일을 못 읽으면 경고 출력. `fake_llm.py`는 테스트용이라 의도적으로 유지.
7. **MCP 로그 Tool**: `mcp_server.py`에 `get_recent_logs` 추가, `data/logs/*.json`은 **합성(가짜) 데이터** — 보고서·발표에서 반드시 밝힐 것.
8. **멀티에이전트**: `PIPELINE=single|multi`. multi는 아래 구조(전부 LangGraph 서브그래프).
9. **평가 도구** `eval/`, **테스트** `tests/`(41개).

### 멀티에이전트 구조 (PIPELINE=multi)
```
부모: route → plan → gate → [research_supervisor] → analysis → write → validate → finalize
총괄 서브그래프: prepare ─(할 일 없음)→ END
                   ├→ metrics ─┐  병렬
                   └→ log ─────┴→ merge → runbook → finish
각 노드 안에서 자기 서브그래프 실행: metrics_agent(fetch) / log_agent(fetch) / runbook_agent(select ─→ read, 매칭 없으면 건너뜀)
```
파일: `agent/agents/{metrics_agent,log_agent,runbook_agent,research_supervisor}.py`, 스위치는 `agent/graph.py`의 `build_graph(deps, pipeline=None)`.
runbook을 수치·로그 수집 뒤에 고르므로 재계획 루프(`replan_check`)가 없다(`replan_rounds` 1 → 0).

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
.venv/bin/python -m pytest tests -q            # 41 passed 가 나와야 함
```

실행(터미널 3개): 백엔드 `bash sh/run_agent_ollma.sh`, 프론트 `bash sh/run_frontend.sh`, 작업용. 브라우저 http://localhost:8600.
- 멀티에이전트로 켜기: `PIPELINE=multi bash sh/run_agent_ollma.sh` (기본은 single)
- 기존 키워드 규칙(Before)으로 켜기: `CLASSIFIER=rules bash sh/run_agent_ollma.sh`

---

## 2. 현재 상태

### 평가 기준값 (single 방식, runbook 선택만 측정)
| 평가 세트 | rules | rag_query | rag_alerts | rag_auto |
|---|---|---|---|---|
| `eval/queries.json` (23문항) | 13/23 | 17/23 | 14/23 | 19/23 |
| `eval/queries_heldout.json` (20문항, `.venv/bin/python eval/run_eval.py eval/queries_heldout.json`) | 10/20 | 15/20 | 10/20 | 17/20 |

(방식별 값이 서로 같게 나오면 `RAG_INPUT` 위치 문제다: 값은 `agent.nodes.replan`에 있다.)

### 아직 확인하지 않은 것 (정직하게)
- **multi가 single보다 정확하거나 빠른지 측정하지 않았다.** `eval/run_eval.py`는 아직 single 흐름만 재현한다.
- 서버(`run_agent_ollma.sh`)를 `PIPELINE=multi`로 띄워 **브라우저에서 확인한 적 없다**(테스트와 스크립트 실행으로만 확인). `web_chat.html`에 추가한 `AgentCompleted` 단계 표시도 눈으로 확인 전.
- 하드코딩 정리 후 평가 기준값 재측정은 아직 안 했다(테스트·import만 확인).

---

## 3. 남은 작업 (우선순위 순)

| 순서 | 할 일 | 비고 |
|---|---|---|
| 1 | 서버를 `PIPELINE=multi`로 띄워 화면 확인 | 단계 표시(메트릭/로그/매뉴얼 에이전트 완료) 확인 |
| 2 | `eval/run_eval.py`를 multi도 측정하게 수정 → **single vs multi 비교** | Before/After 보너스 10점의 핵심. 정확도 동일성(회귀 없음), `replan_rounds`, 시간 |
| 3 | 하드코딩 정리 후 **평가 기준값 재측정** | 위 표와 같아야 함 |
| 4 | **LangSmith 증거**: 한 요청의 트레이스 트리 캡처(총괄 → 에이전트 → MCP 호출), 선택 runbook·점수·`select_ms`를 메타데이터로 | `.env`에서 `LANGCHAIN_TRACING_V2=true`이면 `@traceable`이 이미 기록. 데이터셋 실험은 외부 전송이라 **사전에 본인 확인** |
| 5 | **새 질문 세트**를 만들어 최종 평가 **1회만** 실행 | 기존 43문항은 본 적 있어 과적합 위험. 범위 밖 질문을 더 넣을 것 |
| 6 | HITL·기억 요약은 **설계안만** 기술 | 한계·트레이드오프 |
| 7 | (선택) 시스템 미지정 시 "기본값으로 조회했습니다" 문구 + 테스트 | `finalize_node`, 동작이 바뀌므로 측정 후 |
| 8 | 슬라이드(발표 5분 기준 본문 7–8장), 한계·트레이드오프 정리 | 합성 로그, 얇은 서브그래프(metrics·log는 노드 1개) 명시 |
| 9 | 제출: `.env.example`에 실제 키 없는지 확인, `NEXT_STEPS.md` 정리, GitHub 주소·보고서 주소 등록 | 푸시 전 키 검사 |

시간이 부족하면 줄이는 순서: 7, 5의 규모, 4의 데이터셋 실험. **1, 2, 4(트레이스 캡처)는 지킨다.**

---

## 4. 이미 내린 결정과 알려진 한계

### 결정
- 남은 약점(gateway-service 타임아웃·504 질문 2건 오답, 모호한 구어체, 임계값 취약)은 **한계로 두고** 필수 요소를 끝낸 뒤 시간이 남을 때 본다.
- 멀티에이전트는 설계안이 아니라 **구현**했고, 하위 에이전트는 LangGraph 서브그래프로 만들었다(처음엔 함수 모듈로 만들었다가 전환).
- 모듈화 중에는 동작을 바꾸지 않았다.

### 알려진 한계 (보고서·발표에 정직하게)
- `auto` 방식과 83%는 같은 질문으로 설계해 과적합 위험이 있다(검증용 20문항에서 80→85%로 순위는 유지, 같은 작성자·소표본).
- 임계값 0.5는 임시값에서 출발했고 0.50–0.70 구간만 시험했다. 범위 밖 질문(최대 0.509)과 정답 질문(최소 0.528) 사이 틈이 매우 좁다.
- 시스템 이름은 `xxx-service`, `xxx-숫자` 형식만 인식한다(한글 표현은 못 잡음).
- RAG 색인(`rag.py`)과 시스템 목록 읽기는 MCP를 거치지 않고 파일을 직접 읽는다.
- route 분류는 작은 모델(qwen3:0.6b)이라 가끔 틀리고, 시스템 이름이 있으면 설명을 묻는 질문도 장애 경로로 보정된다.
- `cost_usd`는 글자 수로 어림한 추정치이며 실제 과금이 아니다.
- 로그는 합성 데이터다. metrics·log 서브그래프는 노드가 1개뿐이라 구조상 얇다(분기가 있는 것은 runbook_agent).
- 시스템을 말하지 않으면 `DEFAULT_SYSTEM`(기본 auth-service)을 조용히 조회한다(답변에 표시하지 않음).

---

## 5. 이어서 작업할 때의 규칙 (Claude에게 전달용 맥락)

- 사용자는 **비전공자**이고 코드를 이해하면서 작업하길 원한다. 한 번에 한 단계씩 진행한다.
- 코드나 명령을 줄 때는 묻지 않아도 먼저 **왜 하는지, 무엇을 하는지, 기대 결과**를 최소한의 핵심으로 설명한다.
- 기본은 위치(링크)를 알려 주고 사용자가 직접 붙여넣는 방식이지만, 사용자가 "대신 해줘 / 너가 바꿔줘"라고 한 부분은 직접 수정하고 설명한다. 알리지 않고 앞서 나가지 않는다.
- 모든 수정 뒤에는 `pytest`와 필요한 확인을 돌리고 저장(commit)한다. 되돌리기는 `git restore 파일`.
- 커밋 메시지와 PR 설명에 **공동 작성자(Co-Authored-By 등) 표시를 넣지 않는다.**
- 파이썬 들여쓰기 실수가 잦았다: 붙여넣은 뒤 앞 공백이 사라지지 않았는지, 저장했는지 먼저 확인한다.
- 설계, 계획, 진행 상태는 Notion 페이지에 적어 사용자가 반복해서 묻지 않게 한다.
- 키(.env)는 절대 저장소에 올리지 않는다. 올리기 전 `git grep -n -E "sk-pro[j]-|lsv2_p[t]_"`로 확인(대괄호 표기는 이 줄 자신이 검사에 걸리지 않게 하려는 것).
- 테스트 함수 이름은 영어, 설명은 한글 주석.
