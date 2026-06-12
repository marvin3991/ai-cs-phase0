"""中文斷詞。

設計理由(對應藍圖 §3 檢索策略):PostgreSQL 內建 tsvector 設定檔
無法正確切分中文。常見解法是裝 zhparser 擴充,但官方 pgvector 映像檔
未內建、需自建映像。骨架階段改在應用層用 jieba 斷詞、空白連接後以
'simple' 設定檔建 tsvector,功能等價且不需自製映像。
若日後遷移 Qdrant/自建映像,只需替換本模組與 db schema 的 tsv 欄。
"""
import re

import jieba

_WORD = re.compile(r"^[\w一-鿿]+$")


def tokenize(text: str) -> str:
    """內容端:空白連接的斷詞結果(建 tsvector 用);空字串安全回傳空字串。"""
    if not text or not text.strip():
        return ""
    return " ".join(t.strip() for t in jieba.cut(text, cut_all=False) if t.strip())


def query_tokens(text: str) -> list[str]:
    """查詢端:過濾掉標點,只留字詞(組 OR tsquery 用)。

    為什麼查詢端要 OR:plainto_tsquery 是 AND 語意,中文斷詞在查詢與內容
    兩端常有粒度差(例:查「天」、內容是「天數」),AND 會整查詢落空。
    OR + ts_rank 讓命中較多詞的文件排前面,容錯得多。
    """
    if not text or not text.strip():
        return []
    return [t for t in (s.strip() for s in jieba.cut(text, cut_all=False)) if t and _WORD.match(t)]
