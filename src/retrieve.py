"""混合檢索:向量(cosine)+ 全文(jieba+tsvector)→ RRF 融合。

對應藍圖 §4.2。時效過濾在 SQL 層做(expiry_date),不靠 LLM 自律。
Reranker 尚未接上(藍圖選型為 cross-encoder),骨架先以 RRF 出 top-k,
等評測基線出來後再量測 reranker 帶來的增益。

用法:
    python -m src.retrieve "打樣要幾天?"
"""
import sys

from .db import connect
from .embedder import embed_texts
from .fusion import fuse_rrf
from .tokenize_zh import query_tokens

_ACTIVE = "(expiry_date IS NULL OR expiry_date >= CURRENT_DATE)"


def search(
    conn,
    query: str,
    top_k: int = 5,
    candidates: int = 25,
    permission_levels: list[str] | None = None,
    reranker=None,
) -> list[dict]:
    """混合檢索。permission_levels=None 表示不過濾(Phase 0 內部用);
    Phase 2 接 RBAC 後由呼叫端依使用者身分傳入,如 ['public'] 或 ['public','internal']。
    """
    query = (query or "").strip()
    if not query:
        return []

    perm_sql = ""
    params_extra: tuple = ()
    if permission_levels is not None:
        if not permission_levels:  # 邊界:給了空清單=什麼都不能看,直接回空
            return []
        perm_sql = " AND permission_level = ANY(%s)"
        params_extra = (permission_levels,)

    qvec = embed_texts([query])[0]
    vec_rows = conn.execute(
        f"""SELECT id, doc_id, chunk_no, content, (embedding <=> %s::vector) AS dist
            FROM knowledge_items WHERE {_ACTIVE}{perm_sql}
            ORDER BY dist LIMIT %s""",
        (qvec, *params_extra, candidates),
    ).fetchall()

    # 查詢端用 OR tsquery(理由見 tokenize_zh.query_tokens docstring)
    qtoks = query_tokens(query)
    lex_rows = []
    if qtoks:  # 邊界:斷詞後為空(純符號輸入)→ 跳過全文檢索
        or_query = " | ".join(qtoks)
        lex_rows = conn.execute(
            f"""SELECT id, doc_id, chunk_no, content,
                       ts_rank(tsv, to_tsquery('simple', %s)) AS rank
                FROM knowledge_items
                WHERE tsv @@ to_tsquery('simple', %s) AND {_ACTIVE}{perm_sql}
                ORDER BY rank DESC LIMIT %s""",
            (or_query, or_query, *params_extra, candidates),
        ).fetchall()

    # reranker 掛點:先多取一倍候選,留給 cross-encoder 重排的空間。
    # 尚未接 reranker(藍圖 §3:基線量出來、確認增益後再加),介面先定好。
    fused = fuse_rrf(
        [[r[0] for r in vec_rows], [r[0] for r in lex_rows]],
        top_k=top_k * 2 if reranker else top_k,
    )
    by_id = {r[0]: r for r in vec_rows}
    by_id.update({r[0]: r for r in lex_rows})
    results = [
        {"id": by_id[i][0], "doc_id": by_id[i][1], "chunk_no": by_id[i][2], "content": by_id[i][3]}
        for i in fused
    ]
    if reranker is not None:
        results = reranker(query, results)
    return results[:top_k]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('用法:python -m src.retrieve "你的問題"')
    conn = connect()
    for hit in search(conn, sys.argv[1]):
        print(f"[{hit['doc_id']}#{hit['chunk_no']}] {hit['content'][:80]}…")
