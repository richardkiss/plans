#!/usr/bin/env python3
"""Tests for merge_blocks (no mainnet DB required)."""
import hashlib
import sqlite3

from coin_store import NewCoin
from merge_blocks import merge_blocks, synthetic_block_hash


def _make_coin_id(tag: str) -> bytes:
    return hashlib.sha256(tag.encode()).digest()


def _setup_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE coin_record (
            confirmed_index INTEGER NOT NULL,
            spent_index INTEGER NOT NULL DEFAULT 0,
            timestamp INTEGER NOT NULL,
            coin_name BLOB NOT NULL,
            coin_parent BLOB NOT NULL,
            puzzle_hash BLOB NOT NULL,
            amount BLOB NOT NULL,
            coinbase INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


def _insert_coin(
    conn: sqlite3.Connection,
    *,
    confirmed: int,
    spent: int,
    timestamp: int,
    tag: str,
    amount: int = 1000,
    coinbase: int = 0,
) -> None:
    coin_id = _make_coin_id(tag)
    conn.execute(
        """
        INSERT INTO coin_record
        (confirmed_index, spent_index, timestamp, coin_name, coin_parent,
         puzzle_hash, amount, coinbase)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            confirmed,
            spent,
            timestamp,
            coin_id,
            _make_coin_id(f"{tag}-parent"),
            _make_coin_id(f"{tag}-puzzle"),
            amount.to_bytes(8, "big"),
            coinbase,
        ),
    )


def test_merge_blocks_orders_by_height():
    conn = _setup_db()
    _insert_coin(conn, confirmed=1, spent=0, timestamp=100, tag="a")
    _insert_coin(conn, confirmed=3, spent=0, timestamp=300, tag="b")
    _insert_coin(conn, confirmed=1, spent=2, timestamp=100, tag="a")
    conn.commit()

    blocks = list(merge_blocks(conn, after_height=-1))
    assert [b[0] for b in blocks] == [1, 2, 3]
    assert blocks[0][3][0].coin_id == _make_coin_id("a")
    assert blocks[1][4] == [_make_coin_id("a")]
    assert blocks[0][1] == 100
    assert blocks[1][1] == 100  # spend-only block inherits carry timestamp
    assert blocks[2][1] == 300


def test_merge_blocks_respects_after_height():
    conn = _setup_db()
    _insert_coin(conn, confirmed=1, spent=0, timestamp=100, tag="a")
    _insert_coin(conn, confirmed=2, spent=0, timestamp=200, tag="b")
    conn.commit()

    blocks = list(merge_blocks(conn, after_height=1))
    assert len(blocks) == 1
    assert blocks[0][0] == 2


def test_merge_blocks_max_height():
    conn = _setup_db()
    _insert_coin(conn, confirmed=1, spent=0, timestamp=100, tag="a")
    _insert_coin(conn, confirmed=2, spent=0, timestamp=200, tag="b")
    _insert_coin(conn, confirmed=3, spent=0, timestamp=300, tag="c")
    conn.commit()

    blocks = list(merge_blocks(conn, after_height=-1, max_height=2))
    assert [b[0] for b in blocks] == [1, 2]


def test_synthetic_block_hash_matches_replay():
    height = 42
    expected = hashlib.sha256(str(height).encode()).digest()
    assert synthetic_block_hash(height) == expected
