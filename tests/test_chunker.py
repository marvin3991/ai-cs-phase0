# -*- coding: utf-8 -*-
import pytest

from src.chunker import chunk_text


def test_empty_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_single_chunk():
    assert chunk_text("打樣流程說明。", chunk_size=100, overlap=10) == ["打樣流程說明。"]


def test_all_chunks_within_size():
    text = "這是一句測試。" * 500
    for c in chunk_text(text, chunk_size=200, overlap=30):
        assert len(c) <= 200


def test_overlap_exists_between_chunks():
    text = "甲句內容相當長足以撐出多塊。" * 60
    chunks = chunk_text(text, chunk_size=150, overlap=40)
    assert len(chunks) >= 2
    assert chunks[1].startswith(chunks[0][-40:])


def test_oversized_single_sentence_hard_split():
    text = "無標點" * 300  # 900 字、無句界
    chunks = chunk_text(text, chunk_size=200, overlap=0)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks) == text  # overlap=0 時必須無損重組


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        chunk_text("x", chunk_size=0)
    with pytest.raises(ValueError):
        chunk_text("x", chunk_size=100, overlap=100)
    with pytest.raises(ValueError):
        chunk_text("x", chunk_size=100, overlap=-1)
