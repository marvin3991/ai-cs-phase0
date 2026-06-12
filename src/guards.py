"""硬規則防護層:全部是純函數、可單元測試,對應藍圖 §4.1「寫進程式,不是只寫在 prompt」。

三類防護:
1. 意圖偵測(輸入端):價格/折扣/個案交期承諾 → 不進 LLM,直接轉人工。
2. 金額攔截(輸出端):LLM 回覆出現金額/折數 → 攔下改轉人工(藍圖 §7-12)。
3. injection 偵測(輸入端)與個資遮罩(落庫前)。

邊界已處理:全形數字、千分位、中文數字金額、「300gsm」「三個工作日」不誤攔。
"""
import re

_FULLWIDTH = str.maketrans("0123456789", "0123456789")


def _norm(text: str) -> str:
    return (text or "").translate(_FULLWIDTH)


# ---------- 1. 意圖偵測(輸入端) ----------

_PRICE_INTENT = [
    r"報價", r"價格", r"價錢", r"多少錢", r"幾多錢", r"什麼價",
    r"折扣", r"打.{0,2}折", r"優惠", r"降價", r"便宜(一點|點|些)",
    r"算.{0,6}(錢|價)", r"單價", r"總價", r"費用(多少|怎麼算)",
]
# 個案交期承諾(「打樣一般要幾天」是流程知識、可答;「我這批什麼時候好」是個案承諾、轉人工)
_DELIVERY_COMMIT = [
    r"(我的|我們的|這批|這張單|訂單).{0,12}(什麼時候|何時|幾時|哪時).{0,8}(好|完成|出貨|交貨|拿到)",
    r"交期.{0,4}(承諾|保證|壓)",
]

_INJECTION = [
    r"忽略.{0,8}(設定|指示|提示|規則)", r"無視.{0,8}(指令|規則)",
    r"系統提示", r"提示詞", r"system\s*prompt", r"developer\s*mode",
    r"ignore\s+(previous|all|your)\s+instructions", r"jailbreak", r"越獄",
    r"扮演.{0,12}(開發者|工程師|系統|管理員)",
]


def detect_price_intent(text: str) -> bool:
    t = _norm(text)
    return any(re.search(p, t, re.IGNORECASE) for p in _PRICE_INTENT + _DELIVERY_COMMIT)


def detect_injection(text: str) -> bool:
    t = _norm(text)
    return any(re.search(p, t, re.IGNORECASE) for p in _INJECTION)


# ---------- 2. 金額攔截(輸出端) ----------

_CN_NUM = "一二三四五六七八九十百千萬零兩"
_MONEY = [
    r"NT\$\s*\d", r"NTD\s*\d", r"\$\s*\d",
    rf"\d[\d,]*(\.\d+)?\s*(元|塊)",            # 1,200 元 / 50塊
    rf"(新台幣|台幣)\s*[\d{_CN_NUM}]+",          # 新台幣三萬
    rf"[{_CN_NUM}]+\s*(元|塊錢)",                # 三千元
    r"\d+(\.\d+)?\s*折",                        # 8折 / 8.5折
    rf"[{_CN_NUM}]{{1,3}}\s*折",                 # 七五折
]


def contains_money(text: str) -> bool:
    t = _norm(text)
    return any(re.search(p, t) for p in _MONEY)


# ---------- 3. 個資遮罩(落庫前) ----------

_PII = [
    (re.compile(r"09\d{2}-?\d{3}-?\d{3}"), "[電話已遮罩]"),
    (re.compile(r"0\d{1,2}-\d{6,8}"), "[電話已遮罩]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email已遮罩]"),
    (re.compile(r"\b[A-Z][12]\d{8}\b"), "[身分證已遮罩]"),
]


def redact_pii(text: str) -> str:
    t = _norm(text)
    for pat, repl in _PII:
        t = pat.sub(repl, t)
    return t
