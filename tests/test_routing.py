"""tests/test_routing.py — 질문 분류(route_node)와 경로 분기(_after_route)의 단위 테스트.

LLM은 가짜로 바꿔 끼운다(의존성 주입). route_node는 deps.fast_llm만 사용하므로
SimpleNamespace로 만든 간단한 deps면 충분하다.
"""
import asyncio
from types import SimpleNamespace

from agent.graph import _after_route, route_node


class FakeFastLLM:
    """route()가 항상 정해진 분류를 돌려주는 가짜 모델."""

    def __init__(self, route):
        self._route = route

    def route(self, query):
        return {"route": self._route, "needs_analysis": False}, {"usd": 0.0}


def run_route(query, model_route):
    """모델이 model_route('chat' 또는 'incident')라고 답했을 때 route_node의 결과."""
    deps = SimpleNamespace(fast_llm=FakeFastLLM(model_route))
    return asyncio.run(route_node({"query": query, "events": []}, deps=deps))


# 시스템 이름이 없는 잡담은 모델 판단 그대로 chat으로 간다
def test_keeps_chat_when_no_system_named():
    out = run_route("안녕, 너는 누구야?", "chat")
    assert out["route"] == "chat"
    assert "corrected" not in out["events"][-1]


# 모델이 chat이라 했어도 시스템 이름이 있으면 코드가 incident로 바로잡는다
def test_corrects_chat_to_incident_when_system_named():
    out = run_route("shipping-service 응답이 느려요", "chat")
    assert out["route"] == "incident"
    assert out["events"][-1]["corrected"] is True


# 모델이 이미 incident라 했다면 보정하지 않는다
def test_keeps_incident_without_correction():
    out = run_route("web-01 CPU 급증", "incident")
    assert out["route"] == "incident"
    assert "corrected" not in out["events"][-1]


# route가 chat이면 chat_answer 노드로 간다
def test_after_route_goes_to_chat_answer():
    assert _after_route({"route": "chat", "query": "안녕"}) == "chat_answer"


# 모르는 시스템만 언급하면 조회 없이 unknown_system 노드로 간다
def test_after_route_goes_to_unknown_system_when_only_unknown():
    state = {"route": "incident", "query": "billing-service 응답이 느려요"}
    assert _after_route(state) == "unknown_system"


# 아는 시스템이 하나라도 섞여 있으면 정상 장애 경로(plan)로 간다
def test_after_route_goes_to_plan_when_known_system_present():
    state = {"route": "incident", "query": "payments-service랑 billing-service 둘 다 느려요"}
    assert _after_route(state) == "plan"


# 시스템 이름이 아예 없는 장애 질문도 plan으로 간다
def test_after_route_goes_to_plan_when_no_system_named():
    state = {"route": "incident", "query": "로그인 응답이 느려요"}
    assert _after_route(state) == "plan"
