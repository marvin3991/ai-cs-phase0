-- 僅建立擴充;資料表 schema 由應用程式管理(src/db.py ensure_schema),
-- 避免向量維度在 SQL 與 .env 兩處定義造成不一致。
CREATE EXTENSION IF NOT EXISTS vector;
