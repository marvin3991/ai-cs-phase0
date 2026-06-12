"""資料庫連線與 schema 管理(schema 單一定義處,避免與 SQL 檔不同步)。"""
import os

import psycopg
from pgvector.psycopg import register_vector

from . import config  # noqa: F401


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")
    conn = psycopg.connect(url)
    # 邊界:全新資料庫第一次連線時 vector 型別還不存在,register_vector 會炸。
    # 先嘗試建 extension(已存在=no-op;無權限則交給 register_vector 給出明確錯誤)。
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
    except psycopg.Error:
        conn.rollback()
    register_vector(conn)
    return conn


def ensure_schema(conn: psycopg.Connection, dim: int) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # 邊界:資料表已存在但維度不同 → 明確報錯,禁止默默寫入失敗
    existing = conn.execute(
        """SELECT atttypmod FROM pg_attribute
           WHERE attrelid = to_regclass('knowledge_items') AND attname = 'embedding'"""
    ).fetchone()
    if existing is not None and existing[0] not in (-1, dim):
        raise RuntimeError(
            f"knowledge_items.embedding 既有維度 {existing[0]} 與 EMBEDDING_DIM={dim} 不符。"
            "維度變更必須全量重嵌:備份後 DROP TABLE knowledge_items 再重新匯入。"
        )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS knowledge_items (
            id BIGSERIAL PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_no INT NOT NULL,
            content TEXT NOT NULL,
            content_tokens TEXT NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content_tokens)) STORED,
            embedding vector({dim}),
            version TEXT NOT NULL DEFAULT 'v1',
            effective_date DATE,
            expiry_date DATE,
            permission_level TEXT NOT NULL DEFAULT 'public',
            owner TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (doc_id, chunk_no, version)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ki_tsv ON knowledge_items USING gin (tsv)")
    # 向量索引(HNSW)在資料量小時無感,建議大量匯入後再建:
    # CREATE INDEX idx_ki_emb ON knowledge_items USING hnsw (embedding vector_cosine_ops);
    conn.commit()
