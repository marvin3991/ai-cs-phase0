"""生成層:防護 → 檢索 → 生成 → 輸出檢查 → 附來源。

對應藍圖 §4.1 狀態機的「知識問答」分支與全部硬規則。
retriever / llm 可注入(單元測試不需資料庫),預設接 search 與 llm.chat。

回傳格式(固定,讓管道層好接):
    {"action": "answer"|"handoff"|"refuse", "text": str,
     "sources": [str], "reason": str}

低信心拒答:RAG_MAX_DISTANCE(cosine 距離上限)由 .env 設定。
預設不啟用——門檻必須用真實嵌入跑評測集校準後再訂,憑空設值是編數字。
"""
import os

from . import config  # noqa: F401
from .guards import contains_money, detect_injection, detect_price_intent
from .llm import chat

HANDOFF_PRICE = "價格與交期相關問題需由專人為您確認,已為您轉接客服人員。"
HANDOFF_NO_KNOWLEDGE = "這個問題目前沒有足夠的資料可以回答,已為您轉接客服人員協助。"
REFUSE_INJECTION = "抱歉,這個請求超出客服服務範圍。請問有什麼產品或訂單問題可以協助您?"

_SYSTEM = """你是印刷公司的客服助理。規則:
1. 只能依據下方「知識內容」回答;知識內容沒有的事,回答「目前沒有這項資料」。
2. 嚴禁出現任何價格、金額、折扣數字。
3. 用繁體中文(台灣用語)回覆,簡潔、直接。
4. 不評論同業。"""


def answer(
    user_msg: str,
    retriever=None,
    llm=None,
    conn=None,
    permission_levels: list[str] | None = None,
) -> dict:
    user_msg = (user_msg or "").strip()
    if not user_msg:
        return {"action": "refuse", "text": "請輸入您的問題。", "sources": [], "reason": "empty_input"}

    # 1. 輸入防護(順序:injection 先於價格,攻擊樣本常夾雜價格詞)
    if detect_injection(user_msg):
        return {"action": "refuse", "text": REFUSE_INJECTION, "sources": [], "reason": "injection"}
    if detect_price_intent(user_msg):
        return {"action": "handoff", "text": HANDOFF_PRICE, "sources": [], "reason": "price_intent"}

    # 2. 檢索
    if retriever is None:
        from .retrieve import search as _search

        def retriever(q):  # noqa: F811
            return _search(conn, q, top_k=5, permission_levels=permission_levels)

    hits = retriever(user_msg)
    if not hits:
        return {"action": "handoff", "text": HANDOFF_NO_KNOWLEDGE, "sources": [], "reason": "no_knowledge"}

    # 3. 低信心拒答(門檻未校準前預設關閉;見模組 docstring)
    max_dist = os.environ.get("RAG_MAX_DISTANCE")
    if max_dist is not None:
        dists = [h["dist"] for h in hits if "dist" in h]
        if dists and min(dists) > float(max_dist):
            return {"action": "handoff", "text": HANDOFF_NO_KNOWLEDGE, "sources": [], "reason": "low_confidence"}

    # 4. 生成
    context = "\n\n".join(f"【{h['doc_id']}#{h['chunk_no']}】{h['content']}" for h in hits)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"知識內容:\n{context}\n\n客戶問題:{user_msg}"},
    ]
    reply = (llm or chat)(messages)

    # 5. 輸出防護:回覆出現金額/折數 → 整段攔下轉人工(藍圖 §7-12)
    if contains_money(reply):
        return {"action": "handoff", "text": HANDOFF_PRICE, "sources": [], "reason": "money_in_output"}

    sources = [f"{h['doc_id']}#{h['chunk_no']}" for h in hits]
    return {"action": "answer", "text": reply, "sources": sources, "reason": "ok"}
