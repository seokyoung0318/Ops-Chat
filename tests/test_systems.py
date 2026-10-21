"""tests/test_systems.py — 질문에서 시스템 이름을 뽑는 함수(agent/graph.py)의 단위 테스트."""
from agent.graph import _mentioned_systems, _split_systems


# 'xxx-service' 모양의 이름을 뽑는다
def test_extracts_hyphenated_service_name():
    assert _mentioned_systems("billing-service 응답이 느려요") == ["billing-service"]


# 'xxx-숫자' 모양의 이름(web-01)도 뽑는다
def test_extracts_numbered_host_name():
    assert _mentioned_systems("web-01 CPU 급증") == ["web-01"]


# 하이픈 대신 공백으로 쓴 이름('auth service')을 'auth-service'로 정규화한다
def test_normalizes_space_separated_name():
    assert _mentioned_systems("auth service응답이 느려졌어요.") == ["auth-service"]


# 여러 시스템은 질문에 등장한 순서대로 뽑는다
def test_extracts_multiple_systems_in_order():
    query = "gateway-service에서 payments-service로 타임아웃"
    assert _mentioned_systems(query) == ["gateway-service", "payments-service"]


# 시스템 이름이 없으면 빈 목록을 돌려준다
def test_returns_empty_list_when_no_system_named():
    assert _mentioned_systems("로그인 응답이 느려요") == []


# 모니터링 목록에 있는 시스템(아는 것)과 없는 시스템(모르는 것)을 나눈다
def test_splits_known_and_unknown_systems():
    known, unknown = _split_systems("payments-service랑 billing-service 둘 다 느려요")
    assert known == ["payments-service"]
    assert unknown == ["billing-service"]
