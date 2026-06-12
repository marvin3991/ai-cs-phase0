"""生成層:防護 → 檢索 → 分層回答 → 輸出檢查 → 附來源。

分層回答策略(解決「只能照知識庫回答太狹隘」的問題):
LLM 回覆第一行必須輸出分類標記,程式照標記分流,格式不對一律安全降級轉人工。

  GROUNDED — 知識內容足以回答 → 回答+附來源
  GENERAL  — 知識庫沒有,但屬印刷產業一般常識 → 通識回答+強制免責前綴+記入知識缺口
  HANDOFF  — 涉及本公司具體規格/能力/政策/個案,知識庫沒有 → 轉人工+記入知識缺口
  CHITCHAT — 問候閒聊 → 簡短回應

原則:公司事實絕不用通識瞎答(說錯=錯誤承諾);通識回答是過渡,
每次觸發都記缺口,高頻題由知識營運收編成公司版知識條目。
價格/交期數字硬規則(輸入意圖+輸出金額攔截)對所有分支照常生效。

回傳:{"action": "answer"|"handoff"|"refuse", "text", "sources", "reason"}
"""
import os

from . import config  # noqa: F401
from .guards import contains_money, detect_injection, detect_price_intent
from .llm import chat

HANDOFF_PRICE = "價格與交期相關問題需由專人為您確認,已為您轉接客服人員。"
HANDOFF_NO_KNOWLEDGE = "這個問題需要由專人為您確認,已為您轉接客服人員協助。"
REFUSE_INJECTION = "抱歉,這個請求超出客服服務範圍。請問有什麼產品或訂單問題可以協助您?"
GENERAL_PREFIX = "(以下為一般印刷知識,實際做法以本公司規範與報價單為準)\n"

_SYSTEM = """你是印刷公司的客服助理。你的回覆「第一行」必須是以下四個標記之一,第二行起才是給客戶的內容:

GROUNDED — 下方知識內容足以回答客戶問題時使用;回答只能依據知識內容。
GENERAL — 知識內容與問題無關,但問題屬於印刷產業「一般常識」(名詞解釋、工藝原理、一般流程)時使用;用通識簡潔回答,但嚴禁宣稱本公司有無特定設備、能力或服務。
HANDOFF — 問題涉及「本公司」的具體規格、能力、價格、交期、訂單個案,而知識內容沒有依據時使用;或你無法判斷時使用。第二行不用寫內容。
CHITCHAT — 問候、道謝、閒聊時使用;簡短禮貌回應並引導回印前諮詢服務範圍。

鐵則:
1. 嚴禁出現任何價格、金額、折扣、交期天數的承諾。
2. 客戶問「你們/貴公司」的事,知識內容沒有就用 HANDOFF,不准用一般常識推測本公司做法。
3. 用繁體中文(台灣用語),簡潔、直接。
4. 不評論同業。"""


def _parse_tagged(reply: str) -> tuple[str, str]:
    """解析第一行標記;無法解析回 ('INVALID', 原文)。"""
    lines = (reply or "").strip().split("\n", 1)
    tag = lines[0].strip().upper().rstrip(":")
    body = lines[1].strip() if len(lines) > 1 else ""
    if tag in ("GROUNDED", "GENERAL", "HANDOFF", "CHITCHAT"):
        return tag, body
    return "INVALID", (reply or "").strip()


def _log_gap(conn, question: str, tag: str) -> None:
    """知識缺口記錄(GENERAL/HANDOFF 都記,供每週知識回填檢視)。"""
    if conn is None:
        return
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_gaps (
                id BIGSERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                tag TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
        )
        conn.execute(
            "INSERT INTO knowledge_gaps (question, tag) VALUES (%s, %s)", (question, tag)
        )
        conn.commit()
    except Exception as e:  # 缺口記錄失敗不可影響回覆
        print(f"knowledge_gaps 記錄失敗:{e}")


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

    # 1. 輸入防護(injection 先於價格,攻擊樣本常夾雜價格詞)
    if detect_injection(user_msg):
        return {"action": "refuse", "text": REFUSE_INJECTION, "sources": [], "reason": "injection"}
    if detect_price_intent(user_msg):
        return {"action": "handoff", "text": HANDOFF_PRICE, "sources": [], "reason": "price_intent"}

    # 2. 檢索(向量檢索必有候選,相關與否交給生成層標記判斷)
    if retriever is None:
        from .retrieve import search as _search

        def retriever(q):  # noqa: F811
            return _search(conn, q, top_k=5, permission_levels=permission_levels)

    hits = retriever(user_msg)

    # 3. 低信心直接轉人工(門檻校準後啟用;見 .env RAG_MAX_DISTANCE)
    max_dist = os.environ.get("RAG_MAX_DISTANCE")
    if max_dist is not None and hits:
        dists = [h["dist"] for h in hits if "dist" in h]
        if dists and min(dists) > float(max_dist):
            hits = []

    # 4. 生成(單次呼叫,帶標記協定)
    context = (
        "\n\n".join(f"【{h['doc_id']}#{h['chunk_no']}】{h['content']}" for h in hits)
        if hits
        else "(無相關知識內容)"
    )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"知識內容:\n{context}\n\n客戶問題:{user_msg}"},
    ]
    tag, body = _parse_tagged((llm or chat)(messages))

    # 5. 輸出防護:任何分支出現金額/折數 → 整段攔下轉人工(藍圖 §7-12)
    if body and contains_money(body):
        return {"action": "handoff", "text": HANDOFF_PRICE, "sources": [], "reason": "money_in_output"}

    # 6. 照標記分流;INVALID 一律安全降級轉人工
    if tag == "GROUNDED" and body:
        sources = [f"{h['doc_id']}#{h['chunk_no']}" for h in hits]
        return {"action": "answer", "text": body, "sources": sources, "reason": "ok"}
    if tag == "GENERAL" and body:
        _log_gap(conn, user_msg, "GENERAL")
        return {"action": "answer", "text": GENERAL_PREFIX + body, "sources": [], "reason": "general_knowledge"}
    if tag == "CHITCHAT" and body:
        return {"action": "answer", "text": body, "sources": [], "reason": "chitchat"}
    _log_gap(conn, user_msg, "HANDOFF" if tag == "HANDOFF" else f"INVALID:{tag[:20]}")
    return {"action": "handoff", "text": HANDOFF_NO_KNOWLEDGE, "sources": [], "reason": "no_knowledge" if tag == "HANDOFF" else "invalid_llm_format"}
