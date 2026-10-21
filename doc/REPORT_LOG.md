# 미니프로젝트 작업 로그 (최종 보고서 재료)

> 이 파일은 프로젝트 폴더(all_total_vue_student) **밖**에 둔다 → Git 제출물에 섞이지 않음.
> 작업할 때마다 아래 각 섹션에 사실만 추가한다. 발표는 **5분(준비 포함 최대 6분)** → 본문 슬라이드 7~8장 권장.

## 보고서 순서 (제출 형식) ↔ 이 파일의 섹션
| 보고서 | 이 파일 |
|---|---|
| 1. 주제 간단 설명 | §1 |
| 2. 기능 개선 사항 및 추가 포인트 | §2 |
| 3. 사용한 기술 요소 (+ 구현 화면, 최종 실행 화면 캡처) | §3 |
| 4. (선택) 개선 전/후 수치 (+ 화면 캡처 필수) | §4 |
| 5. 한계 및 트레이드오프 | §5 |

---

## §1 주제 간단 설명
- 운영 인시던트 대응 에이전트(all_total_vue). 장애 신고를 받으면 시스템 상태를 조회(MCP Tool)하고 대응 매뉴얼(runbook, MCP Resource)을 찾아 LLM이 대응 절차를 답한다.
- 구성: FastAPI 백엔드 + LangGraph(노드 10개) + MCP 서버 + Ollama/OpenAI LLM + Vue 채팅 화면 + LangSmith 추적.
- 선택 과제: **1번 (기존 Base AI Agent 개선)**.
- 선택 이유: 이미 동작하는 시스템이라 Before/After 비교가 가능하고, 구조 이해 + 개선에 집중할 수 있음.

## §2 개선 포인트 (Spread 등록안)
| # | 영역 | 무엇을 바꾸나 | 설명 |
|---|---|---|---|
| 1 | RAG | 키워드 기반 장애유형 분류 → RAG 기반 검색 | 기존엔 모니터링 알림의 키워드만 보고 runbook 선택, 사용자 질문 미반영, 매칭 실패 시 db-down 대체. 질문+알림과 의미가 가까운 runbook을 벡터 검색, 임계값 미만이면 "맞는 매뉴얼 없음" |
| 2 | 하드코딩 개선 | 목록에 없는 시스템 질문 시 auth-service 몰래 대체 → "조회 불가" 명시 | 위치: graph.py `_extract_system_name`, ollama_llm.py `_guess_target` |
| 3 | (선택) 모듈화·단위 테스트 | graph.py 분리 + pytest | DI 구조 활용, 가짜 deps로 테스트 |
| 4 | (선택) 데이터 보강 | runbook 6→10종+ | RAG 변별력 확인용 |
| 5 | (선택) 검수 보강 | validate: 수치 인용 확인 | 현재는 "30자 이상 + `1)` 포함"만 확인 |

> 계획 변경 이력: (변경 시 여기에 날짜와 이유 기록)

## §3 사용한 기술 요소
| 기술 요소 | 우리 작업에서의 쓰임 | 상태 |
|---|---|---|
| RAG | runbook 임베딩 + 유사도 검색 (agent/rag.py 예정) | 예정 |
| 의존성 주입 | SupervisorDeps에 retriever 추가 | 예정 |
| MCP | 기존 Tool/Resource/Prompt 유지, runbook 연동 | 기존 |
| LangSmith | 노드별 trace로 분류 결과 확인 | 기존(.env tracing=true) |
| 모듈화 / 단위 테스트 | graph.py 분리, pytest | 예정(선택) |
| Multi-Agent | (현재 범위 밖. "추가 개선"으로 언급 가능) | - |

### 아키텍처 그림
- **Before 아키텍처** (확정): "코드 흐름 한눈에 보기" 그림. 개선 1=replan_check(`_classify_incident_type`), 개선 2=plan(`_extract_system_name`), validate는 (선택). 저장 위치 → `/Users/seokyoung/workspace/week15/report_assets/before_architecture.png` (이미지를 직접 저장해 둘 것)
- **After 아키텍처**: (RAG 연결 후 작성. 추가될 요소: agent/rag.py "사서", deps.retriever, replan_check → retriever.search, 임계값 미만이면 "맞는 매뉴얼 없음")

### 구현 화면 캡처 목록 (작업하며 체크)
- [ ] RAG가 올바른 runbook을 고른 화면
- [ ] "맞는 매뉴얼 없음"/"조회 불가" 응답 화면
- [ ] pytest 통과 화면
- [ ] LangSmith trace 화면
- [ ] 최종 실행 화면

## §4 Before/After 수치
### Before 증거 (확보 완료, 2026-10-20, LLM_BACKEND=ollama, qwen3:0.6b/8b)
| # | 질문 | 관찰된 동작 | 판정 | 약점 |
|---|---|---|---|---|
| 1 | `billing-service 응답이 느려요` | 계획의 시스템이 auth-service로 대체되고, auth-service 수치(CPU 79.1% 등)를 billing의 수치처럼 인용해 답변. "모른다"는 안내 없음. 장애유형은 high-latency | ❌ | 하드코딩 폴백 |
| 2 | `web-01 CPU 급증 원인 진단해줘` | 장애유형 `db-down` 선택(CPU 질문인데 DB 매뉴얼). 답변에 "DB 관련 리소스 확인 필요" 포함. 검수는 통과 | ❌ | 키워드 분류가 질문 무시, 알림 없으면 db-down 대체 |
| 3 | `로그인 응답이 느려요, 원인 확인해주세요` | high-latency 정상 | ✅ (정상 대조군, 알림에 latency/pool 있어 우연히 맞음) | - |
| 4 | `auth service응답이 느려졌어요.` (띄어쓰기 오타) | 시스템명 미인식 → auth-service로 대체(우연히 일치) | △ | 하드코딩 폴백 |

- 추가 관찰: billing-service 답변과 auth-service 답변의 수치(p95 2.4s, 풀 92%)와 문장이 사실상 동일 → 사용자는 다른 시스템 질문에 같은 답을 받아도 알 수 없음(슬라이드용 나란히 비교 캡처 후보)
- 추가 관찰(계획 밖, 부수 이슈): 답변의 `**굵게**` 마크다운이 화면에 별표 그대로 보임(web_chat.html이 마크다운을 렌더링하지 않음)
- 로그인 질문은 시스템명을 말하지 않았는데 시스템: auth-service로 조회됨 → 폴백이 맞아떨어진 우연. 폴백이 틀린 경우를 가려 줌
- 캡처 파일: (이미지 경로를 여기에 적기)
- 측정 항목(After와 같은 조건으로 비교): 장애유형 분류 정확도(라벨된 쿼리 20~30개), 응답 지연시간, retry 횟수, 토큰/비용
- 비교 대상(안): ① 기존 키워드 → ② (대안) 질문도 같이 검사하는 키워드 → ③ (선택) BM25 → ④ Dense RAG
- After 수치: (미측정)
- **RAG 1차 시험 (임베딩 단독 검색, `nomic-embed-text`, 문서 전체 임베딩, 질문만 입력)** — 2026-10-20
  | 질문 | 기대 | 선택(점수) | 판정 |
  |---|---|---|---|
  | web-01 CPU 급증 원인 진단해줘 | cpu-spike | cpu-spike (0.648), 2위 high-latency 0.618 | ✅ (격차 작음) |
  | 서버가 버벅거려요 | high-latency 계열 | auth-failure (0.696) | ❌ |
  | 로그인 응답이 느려요 | high-latency (또는 auth-failure 허용 가능) | auth-failure (0.714), 2위 high-latency 0.697 | △ |
  | 인증서가 만료됐대요 | ssl-cert-expiry | memory-leak (0.683), ssl-cert-expiry는 상위 3위 밖 | ❌ |
  | 배포하고 나서 에러가 폭증했어요 | bad-deploy | bad-deploy (0.705) | ✅ |
  | 점심 메뉴 추천해줘 | 없음(None) | queue-backlog (0.678) | ❌ |
  - 관찰: 모든 점수가 0.60~0.71에 몰려 있고 1·2위 격차가 작음. 무관한 질문(0.678)이 정답 질문(0.648)보다 점수가 높아 **임계값으로 "맞는 매뉴얼 없음"을 가를 수 없음**.
- **RAG 2차 시험 (`bge-m3`, 같은 6문항, 접두어 없음)** — 2026-10-20
  | 질문 | nomic-embed-text | bge-m3 | 판정(bge-m3) |
  |---|---|---|---|
  | web-01 CPU 급증 원인 진단해줘 | cpu-spike 0.648 (2위 0.618) | cpu-spike 0.652 (2위 0.533) | ✅ 격차 0.03→0.12 |
  | 서버가 버벅거려요 | auth-failure 0.696 | auth-failure 0.512 (2위 0.498) | ❌ high-latency가 상위 3위 밖 |
  | 로그인 응답이 느려요 | auth-failure 0.714 | auth-failure 0.613 (2위 queue-backlog 0.610, 3위 high-latency 0.579) | △ 격차 0.003 |
  | 인증서가 만료됐대요 | memory-leak 0.683 (정답 3위 밖) | ssl-cert-expiry 0.681 (2위 0.563) | ✅ |
  | 배포하고 나서 에러가 폭증했어요 | bad-deploy 0.705 (2위 0.687) | bad-deploy 0.605 (2위 0.582) | ✅ (격차 작음) |
  | 점심 메뉴 추천해줘 | queue-backlog 0.678 | 0.412 → threshold 0.5 미만 → None | ✅ |
  - 결과: 명확히 정답 2/6 → 4/6(점심은 None이 정답). 무관 질문 점수가 0.678→0.412로 내려가 **임계값으로 분리 가능해짐**(정답 질문 최저 0.605). 임계값은 0.5로 시험 중이며 표본이 6개뿐이라 라벨 질문 20~30개로 재보정 필요(후보 0.55).
  - 남은 약점: ① "버벅거려요" 같은 모호한 구어체는 오답 ② auth-failure 문서가 여러 질문에서 상위에 오름(내가 일부러 high-latency와 유사하게 만든 문서, 허브처럼 끌어당김) ③ 일부 질문은 1·2위 격차가 매우 작음 ④ bge-m3는 1.2GB로 nomic(274MB)보다 무겁고 지연시간은 미측정.
- **RAG 연결 After 1차 확인 (graph.py `replan_check_node` 교체 후, CLASSIFIER=rag, 채팅 화면)** — 2026-10-20
  - 질문 `web-01 CPU 급증 원인 진단해줘`: 화면에 `정보 부족 → 장애유형 "cpu-spike"로 추가 조사` → `대응 매뉴얼(runbook) 조회 (장애유형: cpu-spike)`. Before(규칙)에서는 `db-down`. → **개선 1 동작 확인**
  - 캡처는 답변 작성 중 화면(캡처 시점에 최종 답변 미완료). 슬라이드용으로는 최종 답변까지 나온 화면을 다시 캡처할 것.
  - 체감 속도 이슈 제기됨: 원인 미확정(가설: 서버 재시작 직후 모델 재로딩, qwen3:8b + bge-m3 동시 상주로 인한 메모리 압박, 임베딩 호출 추가). 측정 필요.
- **After 시간 측정 (CLASSIFIER=rag, ollama qwen3:0.6b/8b, 질문 `web-01 CPU 급증 원인 진단해줘`, 서버 가동 중 연속 3회)** — 2026-10-20
  | 실행 | select_ms (runbook 선택) | 전체 응답(total) | 선택된 runbook(점수) | retry_count | replan_rounds | parallel_elapsed | cost_usd(추정) |
  |---|---|---|---|---|---|---|---|
  | 1 | 73.7 ms | 26.4 s | cpu-spike (0.652) | 0 | 1 | 0.36 s | 0.004371 |
  | 2 | 83.6 ms | 30.1 s | cpu-spike (0.652) | 0 | 1 | 0.35 s | 0.004706 |
  | 3 | 57.8 ms | 23.9 s | cpu-spike (0.652) | 0 | 1 | 0.35 s | 0.004111 |
  | 중앙값 | **73.7 ms** | **26.4 s** | - | 0 | 1 | 0.35 s | 0.004371 |
  - 관찰: RAG의 runbook 선택 비용(약 74 ms)은 전체 응답 시간(약 26 s)의 약 0.3%. 체감 지연의 대부분은 qwen3:8b의 답변 작성(추정).
  - 점수는 3회 모두 0.652로 동일(결정적), 답변 시간과 비용은 실행마다 변동.
  - 주의: cost_usd는 문자열 길이 기반 추정치(코드의 `_usage`)이며 실제 과금이 아님. retry_count는 MCP 클라이언트의 의도적 flaky 데모 때문에 서버 재시작 직후 첫 요청에서만 1이 나올 수 있음(화면에 "재시도 성공"이 보였던 이유로 추정, 측정 프로토콜에서 확인 필요).
- **Before 시간 측정 (CLASSIFIER=rules, 같은 질문·같은 명령·같은 PC, 서버 재시작 직후 연속 3회)** — 2026-10-20
  | 실행 | method | 선택된 runbook | select_ms | 전체 응답(total) | retry_count | replan_rounds | parallel_elapsed | cost_usd(추정) |
  |---|---|---|---|---|---|---|---|---|
  | 1 | rules | **db-down (오답)** | 0.0 ms | 34.7 s (재시작 직후 워밍업) | 1 | 1 | 0.36 s | 0.004826 |
  | 2 | rules | db-down | 0.0 ms | 27.1 s | 0 | 1 | 0.35 s | 0.004141 |
  | 3 | rules | db-down | 0.0 ms | 26.0 s | 0 | 1 | 0.36 s | 0.004026 |
  | 중앙값 | - | db-down | 0.0 ms | 27.1 s | 0 | 1 | 0.36 s | 0.004141 |
- **Before/After 비교 (질문 `web-01 CPU 급증 원인 진단해줘`)**
  | 지표 | Before (rules) | After (rag, bge-m3) | 해석 |
  |---|---|---|---|
  | 선택된 runbook | db-down ❌ | cpu-spike ✅ | 정확도 개선(질문 1건) |
  | runbook 선택 시간 (중앙값) | 0.0 ms | 73.7 ms | 검색 비용 +약 74 ms (임베딩 호출) |
  | 전체 응답 시간 (중앙값) | 27.1 s | 26.4 s | 차이 오차 범위(실행마다 24~30 s로 변동). LLM 답변 작성이 대부분 |
  | replan_rounds | 1 | 1 | 동일(현재 구조에서는 변화 없음) |
  | cost_usd (추정, 중앙값) | 0.004141 | 0.004371 | 차이 미미, 문자열 길이 기반 추정치 |
  - retry_count: Before 실행 1에서만 1(서버 재시작 직후 첫 요청). After 측정은 서버가 이미 가동 중이라 0. → retry는 방식(rules/rag) 차이가 아니라 서버 재시작 직후 데모 장치 때문으로 보임(관찰과 일치, 코드 확인은 안 함). 비교 지표로 부적합.
  - 한계: 질문 1건·각 3회 측정. 정확도는 라벨된 질문 세트(20~30개)로 재측정 필요. 전체 시간 차이는 통계적으로 의미 없음.
  - 결정: 임베딩 모델은 `bge-m3`로 채택(가설 확인: nomic의 한국어 약점).
  - 이전 해석(추정): nomic-embed-text의 한국어 성능 한계 가능성. 검증 계획: 다국어 모델(bge-m3)로 같은 6개 질문 재시험, 문서 임베딩 대상 축소(제목+증상 줄), BM25/하이브리드 비교.

### 데이터 보강(runbook 4종 추가) 선정 근거 — 2026-10-20 웹 검색 (발표 전 링크 직접 열어 확인할 것)
| 추가 runbook | 근거 | 근거 강도 |
|---|---|---|
| bad-deploy | Google SRE Workbook 부록 C(포스트모템 분석): 장애 트리거 중 바이너리 배포 37%, 설정 배포 31% (합 약 68%) https://sre.google/workbook/postmortem-analysis | 강함(공식 자료, 검색 요약 기준이라 표 직접 확인 필요) |
| ssl-cert-expiry | 개별 포스트모템 다수(ImprovMX, Lucidworks, Epic Games, TeamDynamix, python.org): 갱신 자동화가 조용히 실패하거나 알림이 전달되지 않음. 발생 빈도 통계는 못 찾음 | 중간(사례 기반, 빈도 통계 없음) |
| queue-backlog | 런북 템플릿들이 QueueBacklog/ConsumerLag 알림과 컨슈머 확인→독성 메시지 DLQ 격리→스케일 순서를 포함 | 약함~중간(템플릿 자료, 공식 표준 아님) |
| auth-failure | 전용 런북 자료는 못 찾음. 인증 장애는 SEV-1 원인 예시로만 등장. 기존 high-latency와 일부러 비슷하게 둔 "구분 시험용" | 약함(작성자 판단) |
- 형식(증상 → 진단 → 조치 단계)은 일반적인 런북 템플릿 구조("symptom, diagnostic, fix steps, escalation")와 일치.
- 한계로 밝힐 것: 4종 모두 샘플용 가상 절차이며, 새 4종은 기존 키워드 규칙이 구조적으로 못 고르는 주제라 비교가 RAG에 유리함.

### 개선 2 (모르는 시스템 처리) Before 기록 — 2026-10-20, 코드 수정 전
질문 `billing-service 응답이 느려요` (서버: ollama, classifier=rules 모드 — 시스템 처리와 무관), 2회
| 실행 | 조사한 시스템(PlanCreated/TaskCompleted) | 답변 | 전체 시간 | cost_usd(추정) |
|---|---|---|---|---|
| 1 | **auth-service** (billing 아님) → runbook high-latency | "커넥션 풀 사용률 92% 초과, p95 지연 2.4s ..." (auth-service 수치) | 38.2 s | 0.005527 |
| 2 | **auth-service** → high-latency | "p95 지연시간 2.4s, 커넥션 풀 92% ..." | 32.8 s | 0.005293 |
- 문제: 목록에 없는 시스템을 묻는데 "조회 불가" 안내 없이 auth-service의 수치로 답변함.
- 원인 3곳: ① ollama_llm.py plan 프롬프트("언급 없으면 auth-service 기본 조사") ② ollama_llm.py `_guess_target`(목록에 없으면 auth-service) ③ graph.py `_extract_system_name`(폴백 auth-service). openai_llm.py/fake_llm.py에도 유사 구조(미확인).

### 개선 2 After 기록 — 2026-10-20 (시험용 서버 포트 8101, ollama, classifier=rag)
구현: graph.py에 `_mentioned_systems`/`_split_systems`(질문에서 시스템 이름 추출, `auth service`→`auth-service` 정규화), `_after_route`에 3번째 경로, 새 노드 `unknown_system_node`(LLM·MCP 호출 없이 안내문), `finalize_node`에 섞인 질문 안내 문구, web_chat.html `STEP_LABELS`에 `UnknownSystem` 추가.
| 질문 | Before | After |
|---|---|---|
| `billing-service 응답이 느려요` | auth-service 조사 후 auth 수치로 답변, 32.8~38.2 s, cost 0.0053~0.0055 | **"billing-service은(는) 모니터링 대상 목록에 없어 조회할 수 없습니다. 조회 가능한 시스템: ..."**, **1.8 s**, cost 0.00005, task 0건, SSE 스트리밍 경로도 정상(FinalAnswer, DONE) |
| `payments-service랑 billing-service 둘 다 응답이 느려요` | (미측정) | payments-service만 조사 + 답변 끝에 "※ billing-service은(는) 모니터링 대상 목록에 없어 조회하지 않았습니다."(finalize 함수 단독 시험으로 문구 확인) |
| `auth service응답이 느려졌어요.` (공백 오타) | 우연히 정상(폴백이 맞아떨어짐) | 이름 정규화로 `auth-service`를 근거 있게 인식 |
- 부수 효과: 모르는 시스템 질문은 LLM 답변 작성을 건너뛰어 지연 약 32~38 s → 약 1.8 s, 비용 약 99% 감소(추정 cost 기준).
- 한계: 시스템 이름이 `xxx-service`/`xxx-숫자` 형식일 때만 인식. 한글 표현("결제 서비스")이나 이름 없이 모르는 시스템을 가리키는 질문은 못 잡음(기존 auth-service 기본값 동작이 남음). openai_llm/fake_llm의 폴백은 수정하지 않음(graph 단계에서 차단하므로 모르는 시스템만 있는 질문에는 영향 없음).

### 발견·수정: RAG 입력을 '질문만'에서 '질문+알림'으로 — 2026-10-20
- 발견: 개선 2 시험 중, RAG(질문만 입력)가 "응답이 느려요" 계열 질문에서 `queue-backlog`(큐 적체)를 골라 엉뚱한 답변(컨슈머 확대, DLQ 격리)이 나옴. 기존 규칙 방식은 알림 글자(latency, pool)를 봐서 이런 경우 맞았으므로 **RAG가 일부 질문에서 규칙보다 퇴보**. 원인 추정: 새로 추가한 runbook(queue-backlog 등)이 모호한 질문을 끌어당김.
- 검색 단독 시험(알림은 monitoring.json 값):
  | 질문 | 질문만 | 질문+알림 |
  |---|---|---|
  | auth service응답이 느려졌어요 | queue-backlog 0.602 ❌ | high-latency 0.650 ✅ |
  | payments-service랑 billing-service 둘 다 응답이 느려요 | queue-backlog 0.549 ❌ | high-latency 0.603 (2위 cpu-spike 0.592) |
  | 로그인 응답이 느려요 | auth-failure 0.613 (2위 queue-backlog 0.610) | high-latency 0.676 ✅ |
  | web-01 CPU 급증 원인 진단해줘 | cpu-spike 0.652 ✅ | cpu-spike 0.645 ✅ |
- 수정: `replan_check_node`가 `_search_text(state)`(질문 + 조회된 status·alerts)로 검색. `RAG_INPUT=query`로 질문만 쓰는 방식도 켤 수 있음(비교용).
- 서버 통합 확인(재시험): `auth service응답이 느려졌어요.` → high-latency 0.639 (select_ms 70.3), `web-01 CPU 급증 원인 진단해줘` → cpu-spike 0.624 (select_ms 88.2). 답변도 해당 runbook 내용 인용.
- 발표 포인트(개선 과정): ① 규칙 → ② RAG(질문만): web-01 해결, 그러나 모호한 질문에서 퇴보 → ③ RAG(질문+알림): 둘 다 해결. 한계: 알림에 의존하므로 알림이 비어 있는 시스템은 질문이 유일한 단서.
- 추가 관찰: retry_count=1이 서버 시작 후 MCP 도구를 처음 호출하는 요청에서만 나타남(시험 B에서 1, 그 외 0) → "서버 재시작 직후 첫 도구 호출에서만 재시도" 가설과 일치.

### ★ Before/After 정확도 평가 (질문 23문항, 정답 라벨 포함) — 2026-10-21
- 도구: `eval/queries.json`(질문·허용 정답), `eval/run_eval.py`(route→plan→gate→research는 질문당 1회, replan_check만 방식별로 실행, 답변 작성 제외). 결과 원본 `eval/results.json`. 소요 약 85초.
- 구성: 기존 유형 10, 규칙에 불리 1, 새 runbook 5, 모호한 구어체 1, 모르는 시스템 2, 섞인 질문 1, 범위 밖 3(임계값 시험용으로 계획의 20개에 3개 추가).
- 방식: rules(기존 키워드 규칙, Before) / rag_query(질문만) / rag_alerts(항상 질문+알림) / rag_auto(질문에 아는 시스템이 명시된 때만 질문+그 시스템 알림, 아니면 질문만). RAG 임계값 0.5, 임베딩 bge-m3.

| 방식 | 정답 | 정확도 | 평균 select_ms |
|---|---|---|---|
| rules (Before) | 13/23 | 57% | 0.0 |
| rag_query | 17/23 | 74% | 74.6 |
| rag_alerts | 14/23 | 61% | 39.4 |
| **rag_auto (After, 기본값으로 채택)** | **19/23** | **83%** | 37.0 |

| 그룹 | 문항 | rules | rag_query | rag_alerts | rag_auto |
|---|---|---|---|---|---|
| 기존 유형 | 10 | 9 | 7 | 8 | 8 |
| 규칙에 불리(DB) | 1 | 0 | 1 | 0 | 1 |
| 새 runbook | 5 | 0 | 4 | 2 | 4 |
| 모호한 구어체 | 1 | 1 | 0 | 1 | 0 |
| 모르는 시스템 | 2 | 2 | 2 | 2 | 2 |
| 섞인 질문 | 1 | 1 | 0 | 1 | 1 |
| 범위 밖 | 3 | 0 | 3 | 0 | 3 |

임계값별 정확도: 0.50 → rag_query 17 / rag_alerts 14 / rag_auto 19, 0.55 → 15 / 13 / 18, 0.60 → 14 / 10 / 15, 0.65 → 8 / 7 / 8, 0.70 → 5 / 5 / 5.
1위 점수: 정답 일치 질문 최소 0.53(rag_query)·0.549(rag_auto), 범위 밖 질문 0.462~0.496(rag_query/auto) vs 0.625~0.647(rag_alerts).

**정정(중요)**: 앞서 4개 사례만 보고 "질문+알림이 질문만보다 낫다"고 기록했으나 23문항 평가에서는 **반대(61% vs 74%)**. 원인: 시스템 이름이 없는 질문(#11, 13, 15, 21~23)에서 plan이 기본 조회 대상 auth-service를 쓰고, 그 알림(latency, connection pool)이 검색을 high-latency로 오염시킴(기본값 auth-service 문제가 개선 1에서도 재현). 그래서 알림은 질문에 시스템이 명시된 경우에만 사용(rag_auto)하도록 변경, 기본 `RAG_INPUT=auto`.

**해석(발표 시 솔직하게)**
- 개선 성과: 규칙 57% → RAG(auto) 83%. 특히 새 runbook 0/5 → 4/5(규칙은 구조적으로 못 고름), DB 질문, 범위 밖 질문 3/3을 "매뉴얼 없음"으로 판별.
- 규칙이 더 나은 영역: 기존 유형 10문항은 rules 9 > RAG 8, 모호한 구어체(#17)도 rules만 정답. 시스템 이름과 알림이 명확한 경우 규칙이 충분히 좋음.
- 남은 오답(rag_auto 4건): #2·#9(gateway-service 타임아웃/504 → high-latency; 원인 미확정, 알림에 timeout/network 단어가 있음에도), #17(모호한 구어체 → auth-failure 0.512), #12는 route 단계의 작은 모델(qwen3:0.6b)이 장애 질문을 잡담으로 분류한 것(검색과 무관, 모든 방식 공통 오답).
- **과적합 위험**: rag_auto는 같은 23문항 결과를 본 뒤 설계·채택했고 별도 검증 세트가 없음. 임계값 0.5도 범위 밖(≤0.496)과 정답(≥0.526) 사이의 좁은 틈(3개 표본)이라 취약. 질문 수가 적어 83%는 확정 수치가 아님.
- 범위 밖 판별(3/3)은 질문에 아는 시스템이 없을 때 알림 없이 질문만 검색해서 가능했으며, 임계값이 조금만 높아져도 정답이 거부됨(0.55에서 18/23, 0.60에서 15/23).
- 라벨은 작성자(Claude+사용자 검토 예정)가 runbook 내용과 monitoring.json을 근거로 정함. 허용 정답 다수 지정(#7, #10, #17, #20).

### 과적합 확인: 설계 후 새로 쓴 검증 질문 20문항 — 2026-10-21
- 도구: `eval/queries_heldout.json`(id 101~121), `.venv/bin/python eval/run_eval.py eval/queries_heldout.json`, 결과 `eval/results_queries_heldout.json`. 질문은 기존 평가 결과를 반영하지 않고 새로 작성(같은 작성자), 실행은 1회, 결과를 보고 설계를 고치지 않음. 임계값 0.5.
| 방식 | 튜닝 23문항 | 검증 20문항 |
|---|---|---|
| rules (Before) | 13/23 (57%) | 9/20 (45%) |
| rag_query | 17/23 (74%) | 14/20 (70%) |
| rag_alerts | 14/23 (61%) | 9/20 (45%) |
| **rag_auto** | **19/23 (83%)** | **16/20 (80%)** |
- 해석: 방식 간 순위(auto > query > rules, alerts는 query보다 낮음)가 새 질문에서도 유지됨 → 선택한 설계가 23문항에만 맞춰진 우연일 가능성은 낮아 보임. auto 정확도 83% → 80%로 소폭 하락. 다만 (1) 같은 작성자가 두 세트를 모두 썼고, (2) 20문항이라 1문항=5%p, (3) 검증 세트는 시스템 미명시 질문 비중이 높아(8/20) rules가 더 낮게 나오는 등 구성이 달라 직접 비교는 제한적, (4) auto와 query의 차이는 2문항으로 통계적으로 강하지 않음. "과적합이 없다"가 아니라 "심각한 과적합 징후는 보이지 않는다" 수준으로 표현할 것.
- 그룹별(검증): 시스템 명시 rules 6/6, auto 5/6 / 시스템 미명시 rules 1/8, auto 7/8 / 범위 밖 auto 2/3.
- 새로 드러난 약점(설계 반영 전 기록만):
  1. #117 `shipping-service 응답이 느려요`: route의 작은 모델이 chat으로 분류 → 개선 2의 unknown_system 분기가 route=incident에 의존해 작동하지 않음(모든 방식 오답). 시스템 이름이 들어 있어도 잡담으로 빠질 수 있음.
  2. gateway-service 질문: 알림을 넣는 방식에서 network-timeout 대신 high-latency(#105 0.56). 학습 세트의 #2, #9와 같은 현상 → 우연이 아니라 체계적(원인 미확정, 조사 필요).
  3. 모호한 일반 질문(`서비스 응답이 너무 늦어요`)은 질문만 쓰면 queue-backlog로 쏠림(#108). 알림을 넣으면 high-latency로 맞음 → auto가 이 경우엔 손해.
  4. 범위 밖 `노트북 화면이 깜빡거려요`는 0.509로 임계값 0.5를 간신히 넘어 cpu-spike 선택(#121). 임계값 취약성 재확인.
- 앞으로의 평가 원칙: 이번 20문항은 결과를 봤으므로 이후 수정에서는 개발용으로 간주. 최종 보고 전에 새 질문 세트를 한 번 더 만들어 1회만 평가.

### "맞는 매뉴얼 없음" 안내 (개선 1 보완) — 2026-10-20
- 문제: 임계값 미만이면 runbook 없이 조용히 진행하고 사용자에게 알리지 않음(Spread 계획의 "맞는 매뉴얼 없음" 응답이 반쪽 구현).
- 수정: `finalize_node` — ReplanCheck 이벤트에 `matched` 키가 있으면(= 매뉴얼 없음 판단) 답변 끝에 "※ 질문과 일치하는 대응 매뉴얼을 찾지 못해, 조회된 수치만으로 안내했습니다." 추가. `server.py` — `RAG_THRESHOLD` 환경변수(기본 0.5)로 임계값 조절 가능.
- 시험(시험용 서버 8101, RAG_THRESHOLD=0.9, 질문 `web-01 CPU 급증 원인 진단해줘`): ReplanCheck `{'is_sufficient': True, 'method': 'rag', 'score': 0.624, 'matched': None, 'select_ms': 47.8}` → 재조사 없이 진행, `/chat` 답변과 `/chat/stream`의 FinalAnswer 끝에 안내 문구 확인.
- 주의: 임계값 0.5에서는 질문+알림 입력 시 점수가 대체로 0.55 이상이라 이 안내가 실제로 나오는 경우가 드묾(추정). 적정 임계값은 평가 질문 세트로 측정 후 결정.
- 작업 중 이슈: 들여쓰기 실수(5칸)로 `IndentationError` 발생 → 서버 시작 전 `python -c "import agent.graph"`로 문법만 먼저 확인하는 습관 권장.

## §5 한계·트레이드오프 (초안, 작업하며 보강)
- RAG: 임베딩 모델 필요, 검색 지연 추가, 임계값 설정에 따라 오탐/미탐, 유사한 runbook 간 구분 어려움
- runbook이 6~15개 규모면 RAG는 과한 선택일 수 있음 → 키워드+질문 검사가 더 간단한 대안. RAG는 확장성 때문에 선택
- 로컬 모델(qwen3) 응답이 느림, 수치 측정 시 OpenAI와 결과 차이 가능
- 한국어 BM25는 조사/활용형 때문에 약함
- 시스템 목록 기반 판단이라 신규 시스템 추가 시 monitoring.json 갱신 필요
- 추가 개선 후보: Hybrid(BM25+Dense), 문단 단위 청킹, MCP 경유 runbook 로딩, Human-in-the-loop, Research 서브그래프 분리, LLM-as-judge 평가

---

## 진행 로그 (시간순, 사실만)
| 날짜 | 한 일 | 결과/메모 |
|---|---|---|
| 2026-10-20 | 환경 확인: .venv OK, .env 생성(.env.example 이름 변경됨), qwen3:0.6b 추가 pull(qwen3:8b는 기존 보유) | 로컬 Ollama 백엔드로 기동 성공(llm_backend=ollama, v2) |
| 2026-10-20 | 프론트 기동, 채팅 테스트 | 위 Before 증거 4건 확보 |
| 2026-10-20 | 코드 분석 | 약점 위치: graph.py `_classify_incident_type`(키워드+db-down 폴백), `_extract_system_name`(auth-service 폴백), `validate_node`(형식만 검사). 분류가 `state["query"]`를 사용하지 않음 |
| 2026-10-20 | 설계 결정 | RAG는 runbook 선택 단계만 교체(replan_check_node). 새 파일 agent/rag.py + deps/server/graph 연결. 임베딩은 Ollama 임베딩 모델 예정 |
| 2026-10-20 | runbook 4종 추가(ssl-cert-expiry, queue-backlog, bad-deploy, auth-failure) → 총 10종 | 오류 수정용이 아니라 RAG 시험 데이터 보강용(선택 항목). 선정 근거는 §4 아래 표 참고. `ls data/runbooks`로 10개 확인 필요 |
| 2026-10-20 | 설계 결정 정리(아래 "설계 결정 기록" 참고) | 기존 규칙 방식을 검색 방식으로 교체, 규칙은 Before 비교용으로 남김 |
| 2026-10-20 | 임베딩 모델 선정: `nomic-embed-text` (Ollama, 무료, 로컬) | `ollama pull nomic-embed-text` 완료. `ollama list`로 확인: nomic-embed-text:latest, 274 MB |
| | | |

## 핵심 요약: 문제의 원인 코드 (처음 보는 사람용)
**한 줄 요약**: 에이전트가 "어떤 대응 매뉴얼을 펼칠지" 정하는 코드가 사용자 질문은 보지 않고, 키워드 `if`문 몇 개와 마지막 기본값(`db-down`)으로만 판단한다.

**원인 코드** (`agent/graph.py` 의 `_classify_incident_type`)
```python
text = (모니터링 알림 글자들을 이어 붙인 문자열)      # 사용자 질문은 포함되지 않음
for keyword, incident_type in _INCIDENT_TYPE_RULES:   # 키워드 9개를 위에서부터 확인
    if keyword in text:                               # 글자가 들어 있으면
        return incident_type                          #   그 장애유형 선택 (처음 맞는 것이 승리)
return "db-down"                                      # 하나도 안 맞으면 무조건 db-down
```
- 즉 **BM25나 검색이 아니라, 글자 포함 여부만 확인하는 `if`문 규칙**이다.
- `_INCIDENT_TYPE_RULES`는 `("cpu", "cpu-spike")`, `("disk", "disk-full")` 같은 (키워드, 장애유형) 목록이다.
- **`"db-down"`은 문법이 아니라 runbook 파일 이름**(`data/runbooks/db-down.md`, DB 장애 대응 매뉴얼)이다. 장애유형 이름 = runbook 파일 이름. "모르면 DB 장애 매뉴얼"이라는 기본값이 실제로는 엉뚱한 안내를 만든다.

**그래서 생긴 문제 (실측 캡처 있음)**
| 질문 | 결과 | 이유 |
|---|---|---|
| `web-01 CPU 급증 원인 진단해줘` | `db-down` (DB 매뉴얼) | web-01은 알림이 비어 키워드가 안 걸림 → 기본값 db-down. 질문의 "CPU"는 보지 않음 |
| 새로 추가한 runbook(ssl-cert-expiry 등) | 선택 불가 | 규칙 목록에 이름이 없음. 새 유형마다 사람이 키워드를 추가해야 함 |

**개선**: 이 규칙을 의미 기반 검색(Dense, 임베딩)으로 교체한다. 질문과 알림을 함께 벡터로 바꿔 runbook 10개와 유사도를 비교하고, 충분히 비슷한 문서가 없으면 "맞는 매뉴얼 없음"으로 답한다.
- 임베딩 모델: `nomic-embed-text` (Ollama, 무료, 로컬). 글을 "의미 숫자(벡터)"로 바꾸는 전용 모델로, 문장을 생성하지는 않는다. 다운로드 완료 확인(274 MB).
- 기존 규칙은 삭제하지 않고 Before 비교용으로 남긴다.

## 설계 결정 기록
**기존 방식 (Before)**
- `graph.py`의 `_classify_incident_type` + `_INCIDENT_TYPE_RULES`(키워드 9개): 모니터링 알림 글자에 키워드가 있으면 해당 장애유형(= runbook 파일 이름)을 선택하고, 하나도 안 걸리면 `db-down`으로 대체. 사용자 질문은 사용하지 않음.
- 선택된 runbook 본문은 MCP Resource로 읽어 와 LLM 프롬프트에 넣음(증강 생성 부분은 이미 존재, **문서를 찾는 단계만 규칙 기반**).
- 정확한 분류: 단순 부분 문자열 일치(`if keyword in text`)이며 BM25 같은 점수 기반 검색이 아님.

**개선 방식 (After)**
- 문서를 찾는 단계를 의미 기반 검색(Dense, 임베딩 유사도)으로 교체. 입력은 "질문 + 알림". 임계값 미만이면 "맞는 매뉴얼 없음".
- 임베딩 모델: `nomic-embed-text`(Ollama). 문서와 질문을 같은 모델로 벡터화해 코사인 유사도로 비교. 문서 10개라 별도 벡터 DB 없이 인메모리 저장.
- BM25는 임베딩 모델이 필요 없고 단어 겹침 점수로 계산 → **선택(비교용)**. Hybrid(BM25+Dense)는 문서가 많아질 때의 추가 개선으로 언급.
- `_INCIDENT_TYPE_RULES`는 삭제하지 않고 Before 방식으로 남겨, 방식(rules | bm25 | dense)을 바꿔가며 같은 질문 세트로 정확도·지연시간 비교(DI 활용).
- 한국어 임베딩 약점 가능성: 정확도가 낮으면 다국어 모델(`bge-m3`)과 비교하고 결과를 한계에 기록.

## 변경 파일 목록 (내가 만들거나 고친 것 — 원본과 구분하기 위함)
| 파일 | 구분 | 내용 | 상태 |
|---|---|---|---|
| `data/runbooks/ssl-cert-expiry.md`, `queue-backlog.md`, `bad-deploy.md`, `auth-failure.md` | **신규** | RAG 시험용 runbook 4종 추가 | 완료 |
| `agent/rag.py` | **신규** | Dense 검색 모듈(OllamaEmbedder, cosine, RunbookRetriever). 처음 `testrag.py`로 만들었다가 `rag.py`로 이름 변경. 파일 하단 `_demo`는 시험용 | 작성·시험 완료(기본 모델 bge-m3로 변경, 기본값 실행으로 결과 동일 확인), 에이전트 미연결 |
| `agent/deps.py` | 수정 | `SupervisorDeps`에 `retriever: Any = None` 칸 추가(None이면 기존 키워드 규칙 사용) | 완료 |
| `server.py` | 수정 | 서버 시작(lifespan) 시 RunbookRetriever 생성·build(), `CLASSIFIER=rag|rules` 스위치, `EMBED_MODEL`, 준비 실패 시 경고 후 규칙 폴백, `/health`에 `classifier` 표시 | 완료(시작 로그에서 `"classifier": "rag"` 확인) |
| `agent/graph.py` | 수정 | (개선 1) `replan_check_node`: 규칙 → 검색(`deps.retriever`), `select_ms` 측정, 입력을 질문+알림으로(`_search_text`, `RAG_INPUT`). (개선 2) `_mentioned_systems`/`_split_systems`, `_after_route` 3번째 경로 `unknown_system`, 새 노드 `unknown_system_node`, `finalize_node` 안내 문구. `import os, re` 추가 | 완료(시험용 서버 8101에서 확인) |
| `web_chat.html` | 수정 | `STEP_LABELS`에 `UnknownSystem` 문구 추가 | 완료 |

## 용어 (발표 때 쉽게 설명하기 위한 메모)
- RAG: 질문과 의미가 가까운 문서를 먼저 찾아서(Retrieval) 그 내용을 근거로 답하게(Generation) 하는 방식
- 임베딩: 글을 의미를 담은 숫자 목록(벡터)으로 바꾼 것. 숫자가 가까우면 의미가 비슷함
- MCP: AI가 외부 도구/자료에 접근하는 표준 방식 (Tool=조회, Resource=문서, Prompt=절차)
- 의존성 주입: 노드가 필요한 도구(AI, MCP 등)를 직접 만들지 않고 `deps`로 받아 쓰게 하는 구조 → 테스트 시 가짜로 교체 가능
