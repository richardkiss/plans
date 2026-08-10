#!/usr/bin/env python3
"""
Merge per-block coin deltas from two sorted sqlite streams (creations + spends).

One connection, two cursors — same merge logic as extract.py pass 3, without
temp files or the compressed intermediate format.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from typing import TYPE_CHECKING

from coin_store import NewCoin

if TYPE_CHECKING:
    pass

BlockTuple = tuple[int, int, bytes, list[NewCoin], list[bytes]]
ExtractBlockTuple = tuple[int, int, list[bytes], list[bytes]]


def _row_to_record(row: tuple) -> bytes:
    """Serialize one created coin (105 bytes) using sqlite amount bytes as-is."""
    _confirmed_idx, _timestamp, coin_id, coin_parent, puzzle_hash, amount_blob, coinbase = row
    return (
        coin_id
        + coin_parent
        + puzzle_hash
        + amount_blob
        + bytes([coinbase])
    )


def merge_blocks_extract(
    conn: sqlite3.Connection,
    after_height: int,
    max_height: int | None = None,
) -> Iterator[ExtractBlockTuple]:
    """Like merge_blocks but yields extract-format payloads (105-byte coin records)."""
    cre_iter = iter(_creation_cursor(conn, after_height, max_height))
    spe_iter = iter(_spend_cursor(conn, after_height, max_height))

    cre_row = next(cre_iter, None)
    spe_row = next(spe_iter, None)
    carry_timestamp = 0

    while cre_row is not None or spe_row is not None:
        cre_height = cre_row[0] if cre_row is not None else 2**32 - 1
        spe_height = spe_row[0] if spe_row is not None else 2**32 - 1
        height = min(cre_height, spe_height)

        created: list[bytes] = []
        spent: list[bytes] = []
        block_timestamp = 0

        while cre_row is not None and cre_row[0] == height:
            block_timestamp = cre_row[1]
            created.append(_row_to_record(cre_row))
            cre_row = next(cre_iter, None)

        while spe_row is not None and spe_row[0] == height:
            spent.append(spe_row[1])
            spe_row = next(spe_iter, None)

        if block_timestamp == 0:
            block_timestamp = carry_timestamp
        elif block_timestamp != 0:
            carry_timestamp = block_timestamp

        yield height, block_timestamp, created, spent


def synthetic_block_hash(height: int) -> bytes:
    """Match replay.py / spike-replay (not a real header hash)."""
    return hashlib.sha256(str(height).encode()).digest()


def _creation_cursor(
    conn: sqlite3.Connection, after_height: int, max_height: int | None
) -> sqlite3.Cursor:
    cursor = conn.cursor()
    if max_height is not None:
        cursor.execute(
            """
            SELECT confirmed_index, timestamp, coin_name, coin_parent,
                   puzzle_hash, amount, coinbase
            FROM coin_record
            WHERE confirmed_index > ? AND confirmed_index <= ?
            ORDER BY confirmed_index
            """,
            (after_height, max_height),
        )
    else:
        cursor.execute(
            """
            SELECT confirmed_index, timestamp, coin_name, coin_parent,
                   puzzle_hash, amount, coinbase
            FROM coin_record
            WHERE confirmed_index > ?
            ORDER BY confirmed_index
            """,
            (after_height,),
        )
    return cursor


def _spend_cursor(
    conn: sqlite3.Connection, after_height: int, max_height: int | None
) -> sqlite3.Cursor:
    cursor = conn.cursor()
    if max_height is not None:
        cursor.execute(
            """
            SELECT spent_index, coin_name
            FROM coin_record
            WHERE spent_index > 0 AND spent_index > ? AND spent_index <= ?
            ORDER BY spent_index
            """,
            (after_height, max_height),
        )
    else:
        cursor.execute(
            """
            SELECT spent_index, coin_name
            FROM coin_record
            WHERE spent_index > 0 AND spent_index > ?
            ORDER BY spent_index
            """,
            (after_height,),
        )
    return cursor


def _row_to_new_coin(row: tuple) -> NewCoin:
    _confirmed_idx, _timestamp, coin_id, coin_parent, puzzle_hash, amount_blob, coinbase = row
    amount = int.from_bytes(amount_blob, "big") if isinstance(amount_blob, bytes) else amount_blob
    return NewCoin(
        coin_id=coin_id,
        parent=coin_parent,
        puzzle_hash=puzzle_hash,
        amount=amount,
        coinbase=bool(coinbase),
    )


def merge_blocks(
    conn: sqlite3.Connection,
    after_height: int,
    max_height: int | None = None,
) -> Iterator[BlockTuple]:
    """
    Yield (height, timestamp, block_hash, created_coins, spent_coin_ids) in
    ascending height order. ``after_height`` is the last block already applied
    to the target store; emitted blocks are strictly greater than that height.
    """
    cre_iter = iter(_creation_cursor(conn, after_height, max_height))
    spe_iter = iter(_spend_cursor(conn, after_height, max_height))

    cre_row = next(cre_iter, None)
    spe_row = next(spe_iter, None)
    carry_timestamp = 0

    while cre_row is not None or spe_row is not None:
        cre_height = cre_row[0] if cre_row is not None else 2**32 - 1
        spe_height = spe_row[0] if spe_row is not None else 2**32 - 1
        height = min(cre_height, spe_height)

        created: list[NewCoin] = []
        spent: list[bytes] = []
        block_timestamp = 0

        while cre_row is not None and cre_row[0] == height:
            block_timestamp = cre_row[1]
            created.append(_row_to_new_coin(cre_row))
            cre_row = next(cre_iter, None)

        while spe_row is not None and spe_row[0] == height:
            spent.append(spe_row[1])
            spe_row = next(spe_iter, None)

        if block_timestamp == 0:
            block_timestamp = carry_timestamp
        elif block_timestamp != 0:
            carry_timestamp = block_timestamp

        yield (
            height,
            block_timestamp,
            synthetic_block_hash(height),
            created,
            spent,
        )
