"""LLM 呼叫層:可插拔,與 embedder 同一套模式。

LLM_MODE=stub:固定格式回覆,讓管線與防護層不花 API 錢即可測試。
LLM_MODE=api :OpenAI 相容 /v1/chat/completions(直連或經 LiteLLM 閘道)。
"""
import os

import httpx

from . import config  # noqa: F401


def chat(messages: list[dict], mode: str | None = None) -> str:
    mode = mode or os.environ.get("LLM_MODE", "stub")
    if mode == "stub":
        # 取最後一段 user 內容的「客戶問題」段,回固定格式;不做任何「理解」,品質評測必須切 api
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        question = user.split("客戶問題:")[-1].strip()
        return f"(stub 回覆)已依據提供的知識內容回答:{question[:40]}"
    if mode == "api":
        base = os.environ["LLM_API_BASE"].rstrip("/")
        key = os.environ.get("LLM_API_KEY", "")
        model = os.environ["LLM_MODEL"]
        resp = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": messages, "temperature": 0.2},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    raise ValueError(f"未知的 LLM_MODE:{mode}(允許 stub / api)")
