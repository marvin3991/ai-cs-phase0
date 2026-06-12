"""雲端部署進入點:uvicorn src.server:app

與本機 demo 差異:必須外接 PostgreSQL(DATABASE_URL),不用內嵌 pgserver;
多了 /webhook/line、/healthz、/api/diag(部署後驗證憑證用)。
"""
import json
import os
from pathlib import Path

from . import config  # noqa: F401

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL 未設定:雲端部署必須外接 PostgreSQL(pgvector)")

from fastapi import BackgroundTasks, Request  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402

from .answer import answer as _answer  # noqa: E402
from .db import connect, ensure_schema  # noqa: E402
from .demo import create_app  # noqa: E402
from .line_webhook import handle_events, verify_signature  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _bootstrap():
    dim = int(os.environ.get("EMBEDDING_DIM", "1536"))
    conn = connect()
    ensure_schema(conn, dim)
    n = conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
    if n == 0 and os.environ.get("AUTO_INGEST", "1") == "1":
        from .ingest import ingest_dir

        ingest_dir(str(ROOT / "data" / "knowledge_sample"))
    conn.close()


_bootstrap()
app = create_app()


@app.get("/healthz")
def healthz():
    conn = connect()
    try:
        n = conn.execute("SELECT count(*) FROM knowledge_items").fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "knowledge_chunks": n}


@app.post("/webhook/line")
async def line_webhook(request: Request, background: BackgroundTasks):
    body = await request.body()
    sig = request.headers.get("X-Line-Signature", "")
    if not verify_signature(os.environ.get("LINE_CHANNEL_SECRET", ""), body, sig):
        return PlainTextResponse("invalid signature", status_code=403)
    payload = json.loads(body or b"{}")

    def _process():
        def answer_fn(text: str):
            conn = connect()
            try:
                return _answer(text, conn=conn)
            finally:
                conn.close()

        try:
            handle_events(payload, answer_fn)
        except Exception as e:  # 背景任務不可拋出未捕捉例外
            print(f"webhook 處理失敗:{e}")

    background.add_task(_process)
    return {"ok": True}  # 先回 200,處理走背景(LINE 要求 webhook 快速回應)


@app.get("/api/diag")
def diag(token: str = ""):
    """部署後一次性驗證:DB / OpenAI 模型 / LINE token。需 DIAG_TOKEN。"""
    if not os.environ.get("DIAG_TOKEN") or token != os.environ["DIAG_TOKEN"]:
        return PlainTextResponse("forbidden", status_code=403)
    out: dict = {}

    conn = connect()
    try:
        out["db_knowledge_chunks"] = conn.execute(
            "SELECT count(*) FROM knowledge_items"
        ).fetchone()[0]
    finally:
        conn.close()

    import httpx

    try:
        r = httpx.get(
            os.environ.get("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
            timeout=15,
        )
        if r.status_code == 200:
            ids = [m["id"] for m in r.json().get("data", [])]
            out["openai_key"] = "OK"
            out["llm_model_available"] = os.environ.get("LLM_MODEL", "") in ids
            out["embedding_model_available"] = os.environ.get("EMBEDDING_MODEL", "") in ids
            out["model_suggestions"] = sorted(
                i for i in ids if "mini" in i or i.startswith("text-embedding")
            )[:12]
        else:
            out["openai_key"] = f"FAIL {r.status_code}: {r.text[:120]}"
    except Exception as e:
        out["openai_key"] = f"FAIL: {e}"

    try:
        from .line_webhook import get_access_token

        get_access_token()
        out["line_token"] = "OK"
    except Exception as e:
        out["line_token"] = f"FAIL: {e}"
    return out
