"""嵌入層:可插拔設計,換模型不動其他程式。

EMBEDDING_MODE=stub:雜湊假向量。只能驗證管線通不通,
  同文同向量、不同文不同向量,但「沒有語意」——禁止用於真實評測與選型。
EMBEDDING_MODE=api:OpenAI 相容 /v1/embeddings(商用 API 或自架 TEI/vLLM)。

邊界處理:API 回傳維度與 EMBEDDING_DIM 不符時直接報錯,
因為維度不一致寫入 pgvector 會整批失敗,早炸早改。
"""
import hashlib
import math
import os

import httpx

from . import config  # noqa: F401  載入 .env


def embed_texts(texts: list[str], mode: str | None = None, dim: int | None = None) -> list[list[float]]:
    if not texts:
        return []
    mode = mode or os.environ.get("EMBEDDING_MODE", "stub")
    dim = dim or int(os.environ.get("EMBEDDING_DIM", "1024"))
    if mode == "stub":
        return [_stub_vec(t, dim) for t in texts]
    if mode == "api":
        return _embed_api(texts, dim)
    raise ValueError(f"未知的 EMBEDDING_MODE:{mode}(允許 stub / api)")


def _stub_vec(text: str, dim: int) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    vals: list[float] = []
    while len(vals) < dim:
        seed = hashlib.sha256(seed).digest()
        vals.extend(b / 255.0 - 0.5 for b in seed)
    v = vals[:dim]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _embed_api(texts: list[str], dim: int) -> list[list[float]]:
    base = os.environ["EMBEDDING_API_BASE"].rstrip("/")
    key = os.environ.get("EMBEDDING_API_KEY", "")
    model = os.environ["EMBEDDING_MODEL"]
    resp = httpx.post(
        f"{base}/embeddings",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    vecs = [d["embedding"] for d in data]
    for v in vecs:
        if len(v) != dim:
            raise ValueError(
                f"API 回傳維度 {len(v)} 與 EMBEDDING_DIM={dim} 不符;"
                "請修正 .env 後重建資料表再匯入(維度改變必須全量重嵌)"
            )
    return vecs
