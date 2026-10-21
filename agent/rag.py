"""agent/rag.py — runbook 의미 검색 (Dense RAG).

질문과 가장 의미가 가까운 runbook을 찾아 장애유형(= runbook 파일 이름)을 돌려준다.
기존 graph.py의 키워드 규칙(_INCIDENT_TYPE_RULES)을 대체하기 위한 모듈이다.
"""
import asyncio
import sys
import math
from pathlib import Path

import httpx

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "data" / "runbooks"


class OllamaEmbedder:
    """글을 '의미 숫자(벡터)'로 바꿔 주는 도구 — Ollama의 임베딩 모델을 호출한다."""

    def __init__(self, model: str = "bge-m3",
                 base_url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.base_url = base_url


    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self.base_url}/api/embed",
                                  json={"model": self.model, "input": texts})
            r.raise_for_status()
        return r.json()["embeddings"]


def cosine(a: list[float], b: list[float]) -> float:
    """두 벡터가 같은 방향을 가리키는 정도 (1에 가까울수록 의미가 비슷하다)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class RunbookRetriever:
    """runbook 폴더의 문서들을 미리 벡터로 바꿔 두고, 질문과 가까운 순서로 찾아 준다."""
    def __init__(self, embedder, runbook_dir: Path = RUNBOOK_DIR, threshold: float = 0.5,
                 doc_prefix: str = "", query_prefix: str = ""):
        self.embedder = embedder
        self.doc_prefix = doc_prefix        # 문서 앞에 붙일 글자 (모델이 요구할 때만 사용)
        self.query_prefix = query_prefix    # 질문 앞에 붙일 글자
        self.runbook_dir = runbook_dir
        self.threshold = threshold          # 이 점수보다 낮으면 "맞는 매뉴얼 없음"
        self.names: list[str] = []          # 장애유형 이름 (예: "cpu-spike")
        self.vectors: list[list[float]] = []

    async def build(self) -> None:
        """서버 시작 시 1번만 실행 — 모든 runbook을 벡터로 바꿔 저장한다."""
        paths = sorted(self.runbook_dir.glob("*.md"))
        self.names = [p.stem for p in paths]    # 파일 이름에서 .md를 뺀 것
        texts = [self.doc_prefix + p.read_text() for p in paths]
        self.vectors = await self.embedder.embed(texts)

    async def search(self, query: str, top_k: int = 3) -> dict:
        """질문과 가장 가까운 runbook을 찾는다. 점수가 임계값 미만이면 incident_type=None."""
        [qvec] = await self.embedder.embed([self.query_prefix + query])
        ranked = sorted(
            ((cosine(qvec, v), name) for name, v in zip(self.names, self.vectors)),
            reverse=True,
        )[:top_k]
        best_score, best_name = ranked[0]
        return {
            "incident_type": best_name if best_score >= self.threshold else None,
            "score": round(best_score, 3),
            "ranked": [(name, round(score, 3)) for score, name in ranked],
        }


async def _demo() -> None:
    """직접 실행해서 확인하는 용도: 질문별로 어떤 runbook이 몇 점으로 뽑히는지 출력한다."""
    model = sys.argv[1] if len(sys.argv) > 1 else "bge-m3"
    is_nomic = model.startswith("nomic")    # 앞 글자 규칙은 nomic만 필요
    retriever = RunbookRetriever(
        OllamaEmbedder(model),
        doc_prefix="search_document: " if is_nomic else "",
        query_prefix="search_query: " if is_nomic else "",
    )
    print(f"[임베딩 모델: {model}]")
    await retriever.build()

    print(f"runbook {len(retriever.names)}개 로드: {retriever.names}\n")
    queries = [
        "web-01 CPU 급증 원인 진단해줘",
        "서버가 버벅거려요",
        "로그인 응답이 느려요",
        "인증서가 만료됐대요",
        "배포하고 나서 에러가 폭증했어요",
        "점심 메뉴 추천해줘",
    ]
    for q in queries:
        result = await retriever.search(q)
        print(f"Q: {q}")
        print(f"   선택: {result['incident_type']} (점수 {result['score']})")
        print(f"   상위: {result['ranked']}\n")


if __name__ == "__main__":
    asyncio.run(_demo())
