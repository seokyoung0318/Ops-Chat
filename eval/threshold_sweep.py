"""eval/threshold_sweep.py — 임계값을 넓은 구간(0.30~0.74)에서 훑어 보는 분석.

run_eval.py는 임계값 0.50~0.70만 시험했다. 이 스크립트는 평가 때 저장된 결과(eval/results*.json)를 쓴다.
검색기를 threshold=0.0으로 돌려 1위 매뉴얼과 점수를 모두 저장해 두었으므로, 임계값만 바꿔
"그 점수에서 거절했다면 정답이었을까"를 다시 계산할 수 있다 — AI·Ollama 호출 없이 몇 초 안에 끝난다.

실행:  .venv/bin/python eval/threshold_sweep.py
주의:  개발 23문항과 검증 20문항을 합쳐 본 결과라, 여기서 고른 값을 최종 근거로 쓰면 같은 질문에 맞춘 셈이 된다.
       범위 밖 질문은 6개뿐이다. 새 질문 세트로 확인하기 전에는 '최적값'이 아니라 '유력한 구간'으로만 말한다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODE = "rag_auto"
SETS = {"개발 23": ROOT / "results.json", "검증 20": ROOT / "results_queries_heldout.json"}


def predict(r: dict, t: float) -> str:
    m = r["modes"][MODE]
    if r["path"] != "plan":                       # 모르는 시스템·잡담 경로는 검색을 안 쓴다
        return m["target"]
    return m["target"] if (m["score"] or 0) >= t else "none"


def main() -> None:
    sets = {k: json.loads(p.read_text(encoding="utf-8")) for k, p in SETS.items()}
    print("임계값 | 개발23 | 검증20 | 합계43")
    rows = []
    for i in range(30, 76, 2):
        t = i / 100
        a, b = (sum(predict(r, t) in r["expect"] for r in rs) for rs in sets.values())
        rows.append((a + b, t))
        print(f" {t:.2f}  | {a:>2}/23 | {b:>2}/20 | {a + b:>2}/43")
    best = max(c for c, _ in rows)
    print(f"\n합계 최고 {best}/43 → 임계값 {[t for c, t in rows if c == best]}")

    allrs = [r for rs in sets.values() for r in rs]
    ok = sorted((r["modes"][MODE]["score"], r["id"]) for r in allrs
                if r["path"] == "plan" and r["modes"][MODE]["target"] in r["expect"] and "none" not in r["expect"])
    oos = sorted(((r["modes"][MODE]["score"], r["id"], r["query"][:18]) for r in allrs
                  if r["path"] == "plan" and "none" in r["expect"]), reverse=True)
    print("정답 질문 중 점수가 가장 낮은 것:", ok[:2])
    print("범위 밖 질문(점수 높은 순):", oos[:3], f"... 총 {len(oos)}개")


if __name__ == "__main__":
    main()
