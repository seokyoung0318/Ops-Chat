"""agent/agents/decision.py — 조사 총괄의 판단: 질문을 보고 어떤 에이전트를 부를지 정한다.

AI(fast 모델)가 고르고, 형식이 깨지거나 위험한 선택은 코드가 바로잡는다(모델 출력을 그대로 믿지 않는 방식).
세 AI 백엔드(fake/ollama/openai)가 같은 정리 로직을 쓰도록 여기에 모았다. 외부 의존성이 없어 단독으로 테스트할 수 있다.

에이전트 이름: metrics(수치·알림), log(최근 로그), runbook(대응 매뉴얼)
"""
import json
import re

ALL_AGENTS = ("metrics", "log", "runbook")

# 질문에 장애·이상 징후를 나타내는 말이 있는가 → 있으면 원인 조사(로그·매뉴얼)가 필요하다
_TROUBLE = re.compile(r"원인|왜|로그|에러|오류|error|타임아웃|timeout|느려|느리|지연|장애|안\s*돼|끊|급증|폭증|쌓|올라|버벅|문제|이상|다운|불가|실패|만료|배포")
# 단순 현황 확인처럼 보이는 말
_STATUS = re.compile(r"상태|현황|현재|사용률|몇\s*%|얼마")

DECIDE_PROMPT = (
    "당신은 ICT 운영 조사 총괄이다. 사용자 질문에 답하려면 어떤 조사가 필요한지 고르라. "
    "metrics=시스템 수치·알림 조회, log=최근 로그 조회, runbook=대응 매뉴얼 검색. "
    "단순히 현재 상태·수치만 묻는 질문이면 metrics만 고르고, "
    "장애 원인 진단이나 대응 방법을 묻는 질문이면 셋 다 고른다. reason에는 한 줄 이유를 적는다.\n"
    "예시 1) 질문: 'order-gateway 지금 응답 시간 수치 보여줘' → agents=[metrics] (수치만 요청)\n"
    "예시 2) 질문: 'search-api가 왜 자꾸 죽는지 알려줘' → agents=[metrics, log, runbook] (원인 진단 요청)"
)
DECIDE_JSON_HINT = ' JSON 객체로만 응답하라. 스키마: {"agents": ["metrics"|"log"|"runbook", ...], "reason": string}'
AGENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "agents": {"type": "array", "items": {"type": "string", "enum": list(ALL_AGENTS)}},
        "reason": {"type": "string"},
    },
    "required": ["agents", "reason"],
}


def is_status_only(query: str) -> bool:
    """현황만 묻는 질문인가 (장애를 암시하는 말이 없고 상태·사용률 같은 말만 있다)."""
    return bool(_STATUS.search(query)) and not _TROUBLE.search(query)


def rule_decide(query: str, source: str = "rules") -> dict:
    """코드 규칙으로 고른다. fake 모델의 판단이자, AI 출력이 깨졌을 때의 대체값이다."""
    if is_status_only(query):
        return {"agents": ["metrics"], "reason": "현황만 묻는 질문이라 수치만 조회", "source": source}
    return {"agents": list(ALL_AGENTS), "reason": "원인·대응이 필요한 질문이라 전부 조회", "source": source}


def normalize(raw: dict, query: str) -> dict:
    """AI가 고른 에이전트 목록을 정리한다.
    - 모르는 이름은 버린다. 하나도 남지 않으면 규칙으로 대체한다.
    - metrics는 항상 포함한다(매뉴얼 검색 입력과 답변의 기본 근거).
    - 장애 질문이면 runbook은 빼지 못한다(작은 모델이 매뉴얼을 빼먹어 정확도가 떨어지는 것을 막는다)."""
    picked = [a for a in ALL_AGENTS if a in (raw.get("agents") or [])]
    if not picked:
        return rule_decide(query, source="fallback")
    if "metrics" not in picked:
        picked.insert(0, "metrics")
    if not is_status_only(query) and "runbook" not in picked:
        picked.append("runbook")
    agents = [a for a in ALL_AGENTS if a in picked]
    return {"agents": agents, "reason": str(raw.get("reason", ""))[:80], "source": "llm"}


def parse_decision(content: str, query: str) -> dict:
    """AI의 JSON 응답 글자를 판단 결과로 바꾼다. 형식이 깨졌으면 규칙으로 대체한다."""
    try:
        raw = json.loads(content)
        if not isinstance(raw, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError, TypeError):
        return rule_decide(query, source="fallback")
    return normalize(raw, query)
