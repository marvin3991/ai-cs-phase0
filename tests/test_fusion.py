# -*- coding: utf-8 -*-
import pytest

from src.fusion import fuse_rrf


def test_item_in_both_lists_wins():
    vec = ["a", "b", "c"]
    lex = ["d", "b", "e"]
    assert fuse_rrf([vec, lex], top_k=5)[0] == "b"


def test_empty_rankings():
    assert fuse_rrf([[], []]) == []
    assert fuse_rrf([]) == []


def test_top_k_respected():
    assert len(fuse_rrf([["a", "b", "c", "d"]], top_k=2)) == 2


def test_deterministic_tie_break():
    # a 與 b 同分(各在一列同名次)→ 以字串序決勝,結果可重現
    r1 = fuse_rrf([["a"], ["b"]], top_k=2)
    r2 = fuse_rrf([["b"], ["a"]], top_k=2)
    assert r1 == r2 == ["a", "b"]


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        fuse_rrf([["a"]], k=0)
    with pytest.raises(ValueError):
        fuse_rrf([["a"]], top_k=0)
