"""tests/test_decision.py — 조사 총괄의 판단 로직(agent/agents/decision.py)의 단위 테스트. AI 호출 없이 돈다."""
import json

from agent.agents.decision import normalize, parse_decision, rule_decide

STATUS_Q = "web-01 현재 상태 알려줘"
TROUBLE_Q = "cache-service 메모리 사용률이 계속 올라가고 있어요"


# 현황만 묻는 질문은 metrics만 고른다
def test_rule_decide_status_only_picks_metrics():
    assert rule_decide(STATUS_Q)["agents"] == ["metrics"]


# '사용률' 같은 현황 단어가 있어도 장애를 암시하는 말(올라가고)이 있으면 전부 고른다
def test_rule_decide_trouble_wording_overrides_status_words():
    assert rule_decide(TROUBLE_Q)["agents"] == ["metrics", "log", "runbook"]


# 현황도 장애도 아닌 애매한 질문은 안전하게 전부 고른다
def test_rule_decide_ambiguous_question_picks_all():
    assert rule_decide("서버가 이상해요")["agents"] == ["metrics", "log", "runbook"]


# AI가 metrics를 빼먹어도 metrics는 항상 포함된다
def test_normalize_always_includes_metrics():
    out = normalize({"agents": ["log"], "reason": "x"}, STATUS_Q)
    assert out["agents"] == ["metrics", "log"]


# 장애 질문에서 AI가 runbook을 빼먹으면 코드가 되돌려 넣는다 (작은 모델의 누락 방지)
def test_normalize_restores_runbook_for_trouble_question():
    out = normalize({"agents": ["metrics"], "reason": "x"}, TROUBLE_Q)
    assert "runbook" in out["agents"]


# 현황만 묻는 질문에서는 AI의 'metrics만' 선택을 존중한다 (AI의 판단이 실제로 반영된다)
def test_normalize_respects_metrics_only_for_status_question():
    out = normalize({"agents": ["metrics"], "reason": "현황"}, STATUS_Q)
    assert out["agents"] == ["metrics"] and out["source"] == "llm"


# 모르는 이름은 버리고, 유효한 것이 하나도 없으면 규칙으로 대체한다
def test_normalize_falls_back_when_nothing_valid():
    out = normalize({"agents": ["foo", "bar"], "reason": "x"}, TROUBLE_Q)
    assert out["agents"] == ["metrics", "log", "runbook"] and out["source"] == "fallback"


# AI의 응답이 JSON이 아니면 규칙으로 대체한다
def test_parse_decision_falls_back_on_broken_json():
    out = parse_decision("이건 JSON이 아닙니다", STATUS_Q)
    assert out["agents"] == ["metrics"] and out["source"] == "fallback"


# 정상 JSON은 그대로 판단 결과가 된다
def test_parse_decision_accepts_valid_json():
    content = json.dumps({"agents": ["metrics", "log"], "reason": "로그 확인 필요"})
    out = parse_decision(content, STATUS_Q)
    assert out["agents"] == ["metrics", "log"] and out["reason"] == "로그 확인 필요"
