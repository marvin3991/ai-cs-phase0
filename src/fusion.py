"""Reciprocal Rank Fusion(RRF):合併向量檢索與全文檢索的排名。

score(d) = Σ_r 1 / (k + rank_r(d) + 1),k 取常用值 60。
純函數、無外部依賴,單元測試見 tests/test_fusion.py。
"""


def fuse_rrf(rankings: list[list], k: int = 60, top_k: int = 10) -> list:
    if k <= 0:
        raise ValueError("k 必須 > 0")
    if top_k <= 0:
        raise ValueError("top_k 必須 > 0")
    scores: dict = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    # 同分時以字串序決勝,確保結果可重現(評測需要確定性)
    ordered = sorted(scores, key=lambda x: (-scores[x], str(x)))
    return ordered[:top_k]
