"""tests/test_rag.py — runbook 검색기(agent/rag.py)의 단위 테스트.

진짜 임베딩 모델(bge-m3)과 Ollama 없이 돌도록, 임베더를 가짜로 바꿔 끼운다(의존성 주입).
runbook 파일도 pytest가 주는 임시 폴더(tmp_path)에 작은 것을 만들어 쓴다.
"""
import asyncio

import pytest

from agent.rag import RunbookRetriever, cosine


class FakeEmbedder:
    """텍스트에 'cpu', 'disk' 글자가 몇 번 들어 있는지를 벡터로 돌려주는 가짜 임베더."""

    async def embed(self, texts):
        return [[t.lower().count("cpu"), t.lower().count("disk")] for t in texts]


def make_retriever(tmp_path, threshold=0.5):
    """임시 폴더에 runbook 2개를 만들고 검색기를 준비한다."""
    (tmp_path / "cpu-spike.md").write_text("# CPU 급증 cpu cpu", encoding="utf-8")
    (tmp_path / "disk-full.md").write_text("# 디스크 부족 disk disk", encoding="utf-8")
    retriever = RunbookRetriever(FakeEmbedder(), runbook_dir=tmp_path, threshold=threshold)
    asyncio.run(retriever.build())
    return retriever


# 같은 방향의 벡터는 유사도 1
def test_cosine_of_identical_vectors_is_one():
    assert cosine([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)


# 서로 수직인(전혀 다른) 벡터는 유사도 0
def test_cosine_of_orthogonal_vectors_is_zero():
    assert cosine([1, 0], [0, 1]) == 0.0


# 영벡터(내용 없음)는 0으로 처리해 0으로 나누지 않는다
def test_cosine_of_zero_vector_is_zero():
    assert cosine([0, 0], [1, 1]) == 0.0


# build()는 runbook 파일 이름(.md 제외)을 장애유형 이름으로 읽어 들인다
def test_build_loads_runbook_names_from_file_stems(tmp_path):
    retriever = make_retriever(tmp_path)
    assert retriever.names == ["cpu-spike", "disk-full"]


# 질문과 가장 비슷한 runbook을 1위로 돌려준다
def test_search_returns_most_similar_runbook(tmp_path):
    retriever = make_retriever(tmp_path)
    result = asyncio.run(retriever.search("cpu 사용률이 높아요"))
    assert result["incident_type"] == "cpu-spike"
    assert result["ranked"][0][0] == "cpu-spike"


# 다른 runbook이 더 비슷한 질문은 그쪽을 고른다
def test_search_picks_other_runbook_for_other_query(tmp_path):
    retriever = make_retriever(tmp_path)
    result = asyncio.run(retriever.search("disk 공간이 부족해요"))
    assert result["incident_type"] == "disk-full"


# 유사도가 임계값 미만이면 억지로 고르지 않고 None을 돌려준다
def test_search_returns_none_below_threshold(tmp_path):
    retriever = make_retriever(tmp_path)
    result = asyncio.run(retriever.search("프린터가 안 돼요"))   # 겹치는 글자가 없어 점수 0
    assert result["incident_type"] is None
    assert result["score"] == 0.0
