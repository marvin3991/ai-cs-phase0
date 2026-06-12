# -*- coding: utf-8 -*-
"""LINE webhook 純邏輯測試:不打任何外部 API(replier/answer_fn 注入)。"""
import base64
import hashlib
import hmac

from src.line_webhook import FILE_GUIDE, handle_events, is_duplicate, verify_signature

SECRET = "test-secret"


def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()


class TestSignature:
    def test_valid(self):
        body = b'{"events":[]}'
        assert verify_signature(SECRET, body, _sign(body))

    def test_invalid(self):
        assert not verify_signature(SECRET, b"abc", _sign(b"xyz"))

    def test_empty_inputs(self):
        assert not verify_signature(SECRET, b"abc", "")
        assert not verify_signature("", b"abc", "whatever")


def _text_event(text, eid="e1", token="rt1", redelivery=False):
    return {
        "type": "message",
        "webhookEventId": eid,
        "replyToken": token,
        "deliveryContext": {"isRedelivery": redelivery},
        "message": {"type": "text", "text": text},
    }


def _answer_ok(text):
    return {"action": "answer", "text": f"答:{text}", "sources": ["K008#0"], "reason": "ok"}


class TestHandleEvents:
    def test_text_event_replied_with_sources(self):
        sent = []
        n = handle_events(
            {"events": [_text_event("出血要留多少?", eid="a1")]},
            _answer_ok,
            replier=lambda t, m: sent.append((t, m)) or True,
        )
        assert n == 1 and sent[0][0] == "rt1"
        assert "資料來源:K008#0" in sent[0][1]

    def test_duplicate_event_skipped(self):
        sent = []
        payload = {"events": [_text_event("hi", eid="dup1"), _text_event("hi", eid="dup1")]}
        handle_events(payload, _answer_ok, replier=lambda t, m: sent.append(m) or True)
        assert len(sent) == 1

    def test_redelivery_skipped(self):
        sent = []
        handle_events(
            {"events": [_text_event("hi", eid="rd1", redelivery=True)]},
            _answer_ok,
            replier=lambda t, m: sent.append(m) or True,
        )
        assert sent == []

    def test_image_gets_file_guide(self):
        sent = []
        ev = {
            "type": "message",
            "webhookEventId": "img1",
            "replyToken": "rt9",
            "message": {"type": "image"},
        }
        handle_events({"events": [ev]}, _answer_ok, replier=lambda t, m: sent.append(m) or True)
        assert sent == [FILE_GUIDE]

    def test_sticker_ignored(self):
        sent = []
        ev = {"type": "message", "webhookEventId": "st1", "replyToken": "rt8", "message": {"type": "sticker"}}
        handle_events({"events": [ev]}, _answer_ok, replier=lambda t, m: sent.append(m) or True)
        assert sent == []

    def test_handoff_answer_no_sources_line(self):
        sent = []
        fn = lambda text: {"action": "handoff", "text": "已為您轉接客服。", "sources": [], "reason": "price_intent"}
        handle_events({"events": [_text_event("多少錢", eid="p1")]}, fn, replier=lambda t, m: sent.append(m) or True)
        assert "資料來源" not in sent[0]


def test_is_duplicate_window():
    assert not is_duplicate("win-1")
    assert is_duplicate("win-1")
