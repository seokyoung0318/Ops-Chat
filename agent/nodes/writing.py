"""agent/nodes/writing.py — 답변 작성·검수·마무리 노드.

write_node(고품질 모델로 답변 초안 작성), validate_node(코드 기준으로 초안 검수),
finalize_node(최종 답변에 안내 문구 덧붙이기), _after_validate(재작성할지 마무리할지 고르는 갈림길).
graph.py에 있던 것을 분리했다(동작은 그대로).
"""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import AgentState, _cost
from ..systems import _split_systems


@traceable(name="write_node")
async def write_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 8/10a — 고품질 모델로 초안 작성 (1차는 의도적 저품질).

    토큰마다 attempt 번호를 같이 실어 보낸다 — validate가 반려해 재작성(attempt 증가)
    될 때 프론트가 새 말풍선으로 끊어서 보여줄 수 있게 하기 위함(Wave 8 재작성 루프를
    그대로 노출)."""
    attempt = state.get("validation_attempts", 0) + 1
    writer = get_stream_writer()
    draft, usage = await deps.quality_llm.write(
        state["query"], state.get("collected", []),
        attempt, state.get("validation_feedback"),
        on_token=lambda piece: writer(
            {"type": "AnswerToken", "attempt": attempt, "delta": piece}))
    return {"draft": draft, "last_prompt": usage.get("prompt"),
            "cost_usd": _cost(state, usage),
            "events": state["events"] + [{"type": "DraftWritten", "attempt": attempt,
                                          "length": len(draft)}]}


@traceable(name="validate_node")
async def validate_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 8 — 코드 기준 검증: 30자 이상 + 절차 번호 포함이어야 합격."""
    draft = state["draft"]
    attempts = state.get("validation_attempts", 0) + 1
    ok = len(draft) >= 30 and "1)" in draft
    verdict = "합격" if ok else "불합격"
    if not ok and attempts >= 3:   # 실모델 무한 재작성 방지 — 최대 3회 후 통과 처리
        ok, verdict = True, "합격(최대 시도 도달 — 통과 처리)"
    feedback = None if ok else (
        f"응답이 너무 짧습니다({len(draft)}자, 최소 30자). 절차를 1) 2) 3) 번호로 "
        f"구체적으로 설명하세요.")
    event = {"type": "Validation", "attempt": attempts, "verdict": verdict}
    return {"validation_attempts": attempts, "validation_feedback": feedback,
            "events": state["events"] + [event]}


@traceable(name="finalize_node")
async def finalize_node(state: AgentState, deps: SupervisorDeps) -> dict:
    final = state["draft"]
    _, unknown = _split_systems(state["query"])
    if unknown:   # 아는 시스템과 모르는 시스템이 섞인 질문 — 모르는 쪽은 조회하지 않았음을 밝힌다
        final += f"\n\n※ {', '.join(unknown)}은(는) 모니터링 대상 목록에 없어 조회하지 않았습니다."
    if any(e.get("type") == "ReplanCheck" and "matched" in e for e in state["events"]):
        final += "\n\n※ 질문과 일치하는 대응 매뉴얼을 찾지 못해, 조회된 수치만으로 안내했습니다."
    return {"final": final,
            "events": state["events"] + [{"type": "Finalize", "pipeline": "incident-v2"}]}


def _after_validate(state: AgentState) -> str:
    return "finalize" if state.get("validation_feedback") is None else "write"
