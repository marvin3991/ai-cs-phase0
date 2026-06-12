"""切塊器:中文句界切分後合併成塊,帶重疊。

注意:這是字元數版本的起步實作(中文 1 token 約 1~2 字,800 字約略對應
藍圖 §4.2 的 500 token 級距)。語意切塊列為 Phase 0 後段改進項,
評測集分數是改進與否的依據——先量測,再優化。
"""
import re

_SENT_SPLIT = re.compile(r"(?<=[。!?!?\n])")


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size 必須 > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必須在 [0, chunk_size) 區間")
    text = (text or "").strip()
    if not text:
        return []

    sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]

    # 例外:單句超過 chunk_size → 硬切,避免無限大塊
    pieces: list[str] = []
    for s in sentences:
        while len(s) > chunk_size:
            pieces.append(s[:chunk_size])
            s = s[chunk_size:]
        if s:
            pieces.append(s)

    chunks: list[str] = []
    current = ""
    for p in pieces:
        if len(current) + len(p) <= chunk_size:
            current += p
            continue
        if current:
            chunks.append(current)
        tail = current[-overlap:] if (overlap and current) else ""
        current = tail + p
        # 例外:重疊尾段 + 新句仍超過 chunk_size → 硬切
        while len(current) > chunk_size:
            chunks.append(current[:chunk_size])
            current = current[chunk_size:]
    if current:
        chunks.append(current)
    return chunks
