"""知識匯入:讀 data/knowledge_sample/*.md → 切塊 → 斷詞 → 嵌入 → 入庫。

檔名規約:K001_知識名稱.md(K 編號對應「知識來源盤點」工作表的知識編號)。
不符規約的檔案會跳過並警告,不會默默吞掉。
同 doc_id 重新匯入 = 先刪舊塊再寫入(冪等,可重跑)。

用法:
    python -m src.ingest data/knowledge_sample
"""
import os
import re
import sys
from pathlib import Path

from .chunker import chunk_text
from .db import connect, ensure_schema
from .embedder import embed_texts
from .tokenize_zh import tokenize

_FNAME = re.compile(r"^(K\d{3,})_.+\.(md|txt)$")


def ingest_dir(directory: str) -> None:
    root = Path(directory)
    if not root.is_dir():
        raise SystemExit(f"找不到資料夾:{root}")
    files = sorted(root.iterdir())
    if not files:
        raise SystemExit(f"資料夾是空的:{root}")

    dim = int(os.environ.get("EMBEDDING_DIM", "1024"))
    mode = os.environ.get("EMBEDDING_MODE", "stub")
    if mode == "stub":
        print("⚠ EMBEDDING_MODE=stub:假向量僅供管線測試,評測結果不可作為選型依據")

    conn = connect()
    ensure_schema(conn, dim)

    total_chunks = 0
    for f in files:
        if f.is_dir():
            continue
        m = _FNAME.match(f.name)
        if not m:
            print(f"跳過(檔名不符 Kxxx_名稱.md 規約):{f.name}")
            continue
        doc_id = m.group(1)
        text = f.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        if not chunks:
            print(f"跳過(內容為空):{f.name}")
            continue
        vecs = embed_texts(chunks)
        with conn.transaction():
            conn.execute(
                "DELETE FROM knowledge_items WHERE doc_id = %s AND version = 'v1'", (doc_id,)
            )
            for i, (c, v) in enumerate(zip(chunks, vecs)):
                conn.execute(
                    """INSERT INTO knowledge_items
                       (doc_id, chunk_no, content, content_tokens, embedding)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (doc_id, i, c, tokenize(c), v),
                )
        total_chunks += len(chunks)
        print(f"匯入 {doc_id}:{len(chunks)} 塊({f.name})")
    print(f"完成,共 {total_chunks} 塊")


if __name__ == "__main__":
    ingest_dir(sys.argv[1] if len(sys.argv) > 1 else "data/knowledge_sample")
