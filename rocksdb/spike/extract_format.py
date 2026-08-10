#!/usr/bin/env python3
"""Serialization for extract.dat.zst (shared by extract and replay consumers)."""
from __future__ import annotations

import struct
from typing import BinaryIO

from coin_store import NewCoin

COIN_RECORD_SIZE = 105  # coin_id(32) + parent(32) + puzzle_hash(32) + amount(8) + coinbase(1)
BLOCK_HEADER_SIZE = 16  # height(4) + timestamp(8) + n_created(4)


def new_coin_to_record(coin: NewCoin, amount_blob: bytes | None = None) -> bytes:
    """Serialize one created coin (105 bytes), matching extract.py pass 3."""
    if amount_blob is not None:
        amount_bytes = amount_blob
    else:
        amount_bytes = int(coin.amount).to_bytes(8, "big")
    return (
        coin.coin_id
        + coin.parent
        + coin.puzzle_hash
        + amount_bytes
        + bytes([int(coin.coinbase)])
    )


def write_block(
    writer: BinaryIO,
    height: int,
    timestamp: int,
    created_records: list[bytes],
    spent_ids: list[bytes],
) -> None:
    """Write one block record in extract.dat.zst uncompressed format."""
    data = struct.pack(">I", height)
    data += struct.pack(">Q", timestamp)
    data += struct.pack(">I", len(created_records))
    for coin_rec in created_records:
        data += coin_rec
    data += struct.pack(">I", len(spent_ids))
    for coin_id in spent_ids:
        data += coin_id
    writer.write(data)


def read_block_header(header: bytes) -> tuple[int, int, int] | None:
    """Parse block header; return (height, timestamp, n_created) or None if EOF."""
    if not header or len(header) < BLOCK_HEADER_SIZE:
        return None
    return struct.unpack(">IQI", header)
