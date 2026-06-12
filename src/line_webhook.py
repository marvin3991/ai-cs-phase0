"""LINE Messaging API webhook 處理:簽章驗證、事件去重、回覆。

設計對應藍圖 §7:
- §7-5 重複投遞:webhookEventId 記憶體去重(staging 單機夠用;多副本時改 Redis/DB)
- §7-6 reply token:一律用 reply(免費);redelivery 事件 token 已失效,略過
- 非文字訊息(圖片/檔案):回固定收檔引導,不丟給 LLM
"""
import base64
import hashlib
import hmac
import os
import time

import httpx

from . import config  # noqa: F401

LINE_API = "https://api.line.me"
FILE_GUIDE = (
    "已收到您傳送的內容。檔案請以雲端連結提供並開啟共用權限,"
    "檔名註明:訂單編號_品名_版本;印前規範(出血、解析度、色彩模式)都可以直接問我。"
)


def verify_signature(channel_secret: str, body: bytes, signature: str) -> bool:
    if not channel_secret or not signature:
        return False
    mac = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(mac).decode(), signature)


# ---- channel access token:優先用環境變數的長期 token,否則用 ID+Secret 換 stateless token ----
_token_cache = {"token": None, "exp": 0.0}


def get_access_token() -> str:
    static = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if static:
        return static
    now = time.time()
    if _token_cache["token"] and now < _token_cache["exp"] - 60:
        return _token_cache["token"]
    resp = httpx.post(
        f"{LINE_API}/oauth2/v3/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["LINE_CHANNEL_ID"],
            "client_secret": os.environ["LINE_CHANNEL_SECRET"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    d = resp.json()
    _token_cache["token"] = d["access_token"]
    _token_cache["exp"] = now + float(d.get("expires_in", 900))
    return _token_cache["token"]


def reply_message(reply_token: str, text: str) -> bool:
    text = text[:4900]  # LINE 文字上限 5000,留餘裕
    resp = httpx.post(
        f"{LINE_API}/v2/bot/message/reply",
        headers={"Authorization": f"Bearer {get_access_token()}"},
        json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
        timeout=10,
    )
    if resp.status_code != 200:
        # reply token 過期/已用會落在這;staging 記錄即可(正式版接 push fallback + 告警)
        print(f"LINE reply 失敗 {resp.status_code}: {resp.text[:200]}")
        return False
    return True


# ---- webhookEventId 去重(10 分鐘窗口) ----
_seen: dict[str, float] = {}


def is_duplicate(event_id: str) -> bool:
    now = time.time()
    for k, v in list(_seen.items()):
        if now - v > 600:
            _seen.pop(k, None)
    if event_id in _seen:
        return True
    _seen[event_id] = now
    return False


def handle_events(payload: dict, answer_fn, replier=reply_message) -> int:
    """處理 webhook 事件;回傳已回覆則數。answer_fn/replier 可注入(測試不打外部 API)。"""
    replied = 0
    for ev in payload.get("events", []):
        if ev.get("type") != "message":
            continue
        if ev.get("deliveryContext", {}).get("isRedelivery"):
            continue  # 重送事件 reply token 已失效
        eid = ev.get("webhookEventId", "")
        if eid and is_duplicate(eid):
            continue
        token = ev.get("replyToken")
        if not token:
            continue
        mtype = ev.get("message", {}).get("type")
        if mtype == "text":
            text = (ev.get("message", {}).get("text") or "").strip()
            if not text:
                continue
            result = answer_fn(text)
            out = result["text"]
            if result.get("action") == "answer" and result.get("sources"):
                out += "\n— 資料來源:" + ", ".join(result["sources"])
            replied += int(bool(replier(token, out)))
        elif mtype in ("image", "file", "video", "audio"):
            replied += int(bool(replier(token, FILE_GUIDE)))
        # 貼圖等其他類型:不回應
    return replied
