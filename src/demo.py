"""一鍵 Demo:官網聊天視窗 + 印前客服大腦。

    pip install -e ".[demo]"
    python -m src.demo
    → 瀏覽器開 http://localhost:8000

不需要 Docker:沒設 DATABASE_URL 時自動用內嵌 PostgreSQL(pgserver,含 pgvector),
知識庫是空的就自動匯入 data/knowledge_sample。
預設 stub 模式(不花 API 錢):回答品質是假的,但「擋報價、擋 injection、附來源、
轉真人」這些防護行為是真實邏輯——Demo 要看的就是這個。
接真實模型:.env 設 EMBEDDING_MODE=api 與 LLM_MODE=api 及對應端點。
"""
import os
from pathlib import Path

from . import config  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def _bootstrap():
    if not os.environ.get("DATABASE_URL"):
        import pgserver  # 選配依賴:pip install -e ".[demo]"

        srv = pgserver.get_server(str(ROOT / "pgdata"))
        os.environ["DATABASE_URL"] = srv.get_uri()
        print(f"內嵌 PostgreSQL 啟動:{ROOT / 'pgdata'}")

    from .db import connect, ensure_schema

    dim = int(os.environ.get("EMBEDDING_DIM", "1024"))
    conn = connect()
    ensure_schema(conn, dim)
    n = conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
    if n == 0:
        from .ingest import ingest_dir

        ingest_dir(str(ROOT / "data" / "knowledge_sample"))
        n = conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
    conn.close()
    print(f"知識庫就緒:{n} 塊")


def create_app():
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    from .answer import answer
    from .db import connect

    app = FastAPI(title="智慧客服 Demo")

    class ChatIn(BaseModel):
        message: str

    @app.post("/api/chat")
    def chat(inp: ChatIn):
        conn = connect()  # demo 單機:每請求一連線,簡單且執行緒安全
        try:
            return answer(inp.message, conn=conn)
        finally:
            conn.close()

    @app.get("/api/info")
    def info():
        conn = connect()
        try:
            n = conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
        finally:
            conn.close()
        return {
            "llm_mode": os.environ.get("LLM_MODE", "stub"),
            "embedding_mode": os.environ.get("EMBEDDING_MODE", "stub"),
            "knowledge_chunks": n,
        }

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (ROOT / "demo" / "index.html").read_text(encoding="utf-8")

    return app


def main():
    import uvicorn

    _bootstrap()
    port = int(os.environ.get("DEMO_PORT", "8000"))
    print(f"Demo:http://localhost:{port}")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
