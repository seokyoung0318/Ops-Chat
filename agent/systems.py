"""agent/systems.py — 모니터링 대상 시스템 목록과, 질문에서 시스템 이름을 뽑는 함수.

graph.py에 섞여 있던 시스템 이름 처리를 한곳으로 모았다(동작은 그대로).
"""
import json
import re
from pathlib import Path


def _load_known_systems() -> set[str]:
    """data/monitoring.json의 시스템 이름들을 읽는다 (ollama_llm.py/openai_llm.py와 동일한 소스)."""
    path = Path(__file__).resolve().parent.parent / "data" / "monitoring.json"
    try:
        return set(json.loads(path.read_text()).keys())
    except (OSError, json.JSONDecodeError):
        return {"auth-service", "web-01"}


KNOWN_SYSTEMS = _load_known_systems()

# '이름-service' 또는 '이름-숫자'(예: web-01) 모양의 글자를 시스템 이름 후보로 본다.
# 앞의 (?<!...)는 한글 바로 뒤에 붙은 영어 이름(예: '의billing-service')도 잡기 위한 장치.
_SYSTEM_RE = re.compile(
    r"(?<![A-Za-z0-9-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*-(?:service|\d+)", re.I)


def _mentioned_systems(query: str) -> list[str]:
    """질문에 언급된 시스템 이름 후보를 뽑는다 (예: 'billing-service', 'web-01').
    'auth service'처럼 하이픈 대신 공백으로 쓴 경우도 'auth-service'로 정규화한다."""
    normalized = re.sub(r"([A-Za-z0-9]+)\s+service", r"\1-service", query, flags=re.I)
    found = [m.group(0).lower() for m in _SYSTEM_RE.finditer(normalized)]
    return list(dict.fromkeys(found))   # 중복 제거, 순서 유지


def _split_systems(query: str) -> tuple[list[str], list[str]]:
    """질문에 언급된 시스템을 (아는 시스템, 모르는 시스템)으로 나눈다."""
    mentioned = _mentioned_systems(query)
    known = [s for s in mentioned if s in KNOWN_SYSTEMS]
    unknown = [s for s in mentioned if s not in KNOWN_SYSTEMS]
    return known, unknown

def _extract_system_name(query: str) -> str:
    """정규식 대신 실제 KNOWN_SYSTEMS 멤버십 매칭 — MCP Prompt(incident_analysis_
    prompt)의 system_name은 "시스템: X" 한 줄짜리 컨텍스트라 항상 정해진 이름
    중 하나로만 고정한다(여러 개 언급돼도 join하지 않음 — 실제 조사 대상 목록은
    이후 plan()의 tasks가 별도로 결정). 쿼리에서 가장 먼저 등장하는 시스템을
    고르고, 하나도 안 걸리면 가장 흔한 사례인 auth-service로 폴백."""
    matches = [(query.index(s), s) for s in KNOWN_SYSTEMS if s in query]
    return min(matches)[1] if matches else "auth-service"