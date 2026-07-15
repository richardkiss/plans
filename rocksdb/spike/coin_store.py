#!/usr/bin/env python3
"""
Uniform CoinStore API with four implementations:
1. sqlite-full: Production schema with all indexes
2. sqlite-consensus: Same minus explorer indexes  
3. rocks: RocksDB with spent coins kept (flag update)
4. rocks-lean: RocksDB with spent coins deleted (full records in undo)
"""
import dataclasses
import sqlite3
import struct
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from chia_rs import CoinRecord, Coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

try:
    from rocksdict import Rdict, WriteBatch
except ImportError:
    Rdict = None
    WriteBatch = None


@dataclasses.dataclass(frozen=True)
class NewCoin:
    """A coin being created."""
    coin_id: bytes
    parent: bytes
    puzzle_hash: bytes
    amount: int
    coinbase: bool


class CoinStore(Protocol):
    """Uniform coin store interface."""
    
    def process_spends(
        self,
        block_index: int,
        block_hash: bytes,
        timestamp: int,
        new_coins: list[NewCoin],
        spent_coin_ids: list[bytes],
    ) -> list[CoinRecord]:
        """
        Atomically: insert creations, mark/delete spends, write undo info, update peak.
        Returns the spent CoinRecords.
        Raises if a spent coin is missing or already spent.
        Must handle ephemeral coins (created and spent in the same block).
        """
        ...
    
    def rewind_to_block(self, block_index: int) -> None:
        """
        Atomically undo everything above block_index, including peak.
        Undo records above block_index must be removed.
        """
        ...
    
    def get_coin_records(self, coin_ids: list[bytes]) -> list[CoinRecord | None]:
        """Get coin records by ID. Returns None for missing coins."""
        ...
    
    def peak(self) -> tuple[int, bytes] | None:
        """Return (height, block_hash) of peak, or None if empty."""
        ...
    
    def close(self) -> None:
        """Close the store."""
        ...
    
    def db_size(self) -> int:
        """Return database size in bytes."""
        ...
    
    def num_coins(self) -> int:
        """Return number of coins in the database (spent + unspent)."""
        ...


class SqliteFullStore:
    """
    SQLite store with full production schema (all 4 indexes).
    Spent coins are kept with spent_index updated.
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self._create_schema()
    
    def _create_schema(self):
        """Create the full production schema."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS coin_record (
                coin_name BLOB PRIMARY KEY,
                confirmed_index INTEGER NOT NULL,
                spent_index INTEGER NOT NULL DEFAULT 0,
                coinbase INTEGER NOT NULL,
                puzzle_hash BLOB NOT NULL,
                coin_parent BLOB NOT NULL,
                amount BLOB NOT NULL,
                timestamp INTEGER NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS coin_confirmed_index ON coin_record(confirmed_index);
            CREATE INDEX IF NOT EXISTS coin_spent_index ON coin_record(spent_index);
            CREATE INDEX IF NOT EXISTS coin_puzzle_hash ON coin_record(puzzle_hash);
            CREATE INDEX IF NOT EXISTS coin_parent ON coin_record(coin_parent);
            
            CREATE TABLE IF NOT EXISTS block_undo (
                height INTEGER PRIMARY KEY,
                block_hash BLOB NOT NULL,
                timestamp INTEGER NOT NULL,
                created_ids BLOB NOT NULL,
                spent_ids BLOB NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS peak (
                id INTEGER PRIMARY KEY CHECK (id = 0),
                height INTEGER NOT NULL,
                block_hash BLOB NOT NULL
            );
        """)
        self.conn.commit()
    
    def process_spends(
        self,
        block_index: int,
        block_hash: bytes,
        timestamp: int,
        new_coins: list[NewCoin],
        spent_coin_ids: list[bytes],
    ) -> list[CoinRecord]:
        with self.conn:
            # Look up coins being spent (may be ephemeral)
            spent_records = []
            ephemeral = {}  # coins created in this block
            
            # Insert new coins
            for nc in new_coins:
                coin = Coin(bytes32(nc.parent), bytes32(nc.puzzle_hash), uint64(nc.amount))
                coin_id = bytes(coin.name())
                
                self.conn.execute("""
                    INSERT INTO coin_record 
                    (coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp)
                    VALUES (?, ?, 0, ?, ?, ?, ?, ?)
                """, (coin_id, block_index, 1 if nc.coinbase else 0, nc.puzzle_hash, nc.parent,
                      nc.amount.to_bytes(8, 'big'), timestamp))
                
                # Track for ephemeral detection
                cr = CoinRecord(coin, uint32(block_index), uint32(0), nc.coinbase, uint64(timestamp))
                ephemeral[coin_id] = cr
            
            # Mark spends
            for coin_id in spent_coin_ids:
                # Check if ephemeral
                if coin_id in ephemeral:
                    cr = ephemeral[coin_id]
                    # Update it as spent
                    cr = CoinRecord(cr.coin, cr.confirmed_block_index, uint32(block_index), 
                                  cr.coinbase, cr.timestamp)
                    spent_records.append(cr)
                    self.conn.execute("UPDATE coin_record SET spent_index = ? WHERE coin_name = ?",
                                    (block_index, coin_id))
                else:
                    # Look up existing coin
                    row = self.conn.execute(
                        "SELECT coin_parent, puzzle_hash, amount, confirmed_index, spent_index, coinbase, timestamp "
                        "FROM coin_record WHERE coin_name = ?", (coin_id,)).fetchone()
                    
                    if row is None:
                        raise ValueError(f"Spent coin {coin_id.hex()} not found")
                    
                    coin_parent, puzzle_hash, amount_blob, confirmed_idx, spent_idx, coinbase, ts = row
                    
                    if spent_idx != 0:
                        raise ValueError(f"Coin {coin_id.hex()} already spent at height {spent_idx}")
                    
                    # Update as spent
                    self.conn.execute("UPDATE coin_record SET spent_index = ? WHERE coin_name = ?",
                                    (block_index, coin_id))
                    
                    coin = Coin(bytes32(coin_parent), bytes32(puzzle_hash), 
                               uint64.from_bytes(amount_blob))
                    cr = CoinRecord(coin, uint32(confirmed_idx), uint32(block_index), bool(coinbase), uint64(ts))
                    spent_records.append(cr)
            
        # Write undo info  
        created_ids_blob = b"".join(bytes(Coin(bytes32(nc.parent), bytes32(nc.puzzle_hash), uint64(nc.amount)).name()) for nc in new_coins)
        spent_ids_blob = b"".join(spent_coin_ids)
        self.conn.execute("""
            INSERT INTO block_undo (height, block_hash, timestamp, created_ids, spent_ids)
            VALUES (?, ?, ?, ?, ?)
        """, (block_index, block_hash, timestamp, created_ids_blob, spent_ids_blob))
        
        # Update peak
        self.conn.execute("""
            INSERT OR REPLACE INTO peak (id, height, block_hash)
            VALUES (0, ?, ?)
        """, (block_index, block_hash))
        
        return spent_records
    
    def rewind_to_block(self, block_index: int) -> None:
        with self.conn:
            # Get all undo records above target
            rows = self.conn.execute("""
                SELECT height, created_ids, spent_ids
                FROM block_undo
                WHERE height > ?
                ORDER BY height DESC
            """, (block_index,)).fetchall()
            
            for height, created_ids_blob, spent_ids_blob in rows:
                # Delete created coins
                for i in range(0, len(created_ids_blob), 32):
                    coin_id = created_ids_blob[i:i+32]
                    self.conn.execute("DELETE FROM coin_record WHERE coin_name = ?", (coin_id,))
                
                # Unspend spent coins
                for i in range(0, len(spent_ids_blob), 32):
                    coin_id = spent_ids_blob[i:i+32]
                    self.conn.execute("UPDATE coin_record SET spent_index = 0 WHERE coin_name = ?", (coin_id,))
                
                # Delete undo record
                self.conn.execute("DELETE FROM block_undo WHERE height = ?", (height,))
            
            # Update peak
            self.conn.execute("""
                INSERT OR REPLACE INTO peak (id, height, block_hash)
                VALUES (0, ?, ?)
            """, (block_index, b"\x00" * 32))
    
    def get_coin_records(self, coin_ids: list[bytes]) -> list[CoinRecord | None]:
        results = []
        for coin_id in coin_ids:
            row = self.conn.execute("""
                SELECT coin_parent, puzzle_hash, amount, confirmed_index, spent_index, coinbase, timestamp
                FROM coin_record WHERE coin_name = ?
            """, (coin_id,)).fetchone()
            
            if row is None:
                results.append(None)
            else:
                coin_parent, puzzle_hash, amount_blob, confirmed_idx, spent_idx, coinbase, timestamp = row
                coin = Coin(bytes32(coin_parent), bytes32(puzzle_hash), uint64.from_bytes(amount_blob))
                cr = CoinRecord(coin, uint32(confirmed_idx), uint32(spent_idx), bool(coinbase), uint64(timestamp))
                results.append(cr)
        
        return results
    
    def peak(self) -> tuple[int, bytes] | None:
        row = self.conn.execute("SELECT height, block_hash FROM peak WHERE id = 0").fetchone()
        return (row[0], row[1]) if row else None
    
    def close(self) -> None:
        self.conn.close()
    
    def db_size(self) -> int:
        return self.db_path.stat().st_size
    
    def num_coins(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM coin_record").fetchone()[0]


class SqliteConsensusStore(SqliteFullStore):
    """
    SQLite store without explorer indexes (puzzle_hash, coin_parent).
    """
    
    def _create_schema(self):
        """Create schema without explorer indexes."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS coin_record (
                coin_name BLOB PRIMARY KEY,
                confirmed_index INTEGER NOT NULL,
                spent_index INTEGER NOT NULL DEFAULT 0,
                coinbase INTEGER NOT NULL,
                puzzle_hash BLOB NOT NULL,
                coin_parent BLOB NOT NULL,
                amount BLOB NOT NULL,
                timestamp INTEGER NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS coin_confirmed_index ON coin_record(confirmed_index);
            CREATE INDEX IF NOT EXISTS coin_spent_index ON coin_record(spent_index);
            
            CREATE TABLE IF NOT EXISTS block_undo (
                height INTEGER PRIMARY KEY,
                block_hash BLOB NOT NULL,
                timestamp INTEGER NOT NULL,
                created_ids BLOB NOT NULL,
                spent_ids BLOB NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS peak (
                id INTEGER PRIMARY KEY CHECK (id = 0),
                height INTEGER NOT NULL,
                block_hash BLOB NOT NULL
            );
        """)
        self.conn.commit()


class RocksStore:
    """
    RocksDB store with spent coins kept (flag updated).
    Schema:
    - c<coin_id> -> CoinRecord (bytes)
    - b<height> -> undo info (timestamp + created_ids + spent_ids)
    - p -> peak (height(4) + block_hash(32))
    """
    
    def __init__(self, db_path: Path):
        if Rdict is None:
            raise ImportError("rocksdict not available")
        
        self.db_path = db_path
        self.db = Rdict(str(db_path))
    
    def process_spends(
        self,
        block_index: int,
        block_hash: bytes,
        timestamp: int,
        new_coins: list[NewCoin],
        spent_coin_ids: list[bytes],
    ) -> list[CoinRecord]:
        batch = WriteBatch()
        spent_records = []
        ephemeral = {}
        
        # Insert new coins
        for nc in new_coins:
            coin = Coin(bytes32(nc.parent), bytes32(nc.puzzle_hash), uint64(nc.amount))
            cr = CoinRecord(coin, uint32(block_index), uint32(0), nc.coinbase, uint64(timestamp))
            batch.put(b"c" + nc.coin_id, bytes(cr))
            ephemeral[nc.coin_id] = cr
        
        # Mark spends
        for coin_id in spent_coin_ids:
            if coin_id in ephemeral:
                cr = ephemeral[coin_id]
                cr = CoinRecord(cr.coin, cr.confirmed_block_index, uint32(block_index),
                              cr.coinbase, cr.timestamp)
                spent_records.append(cr)
                batch.put(b"c" + coin_id, bytes(cr))
            else:
                coin_blob = self.db.get(b"c" + coin_id)
                if coin_blob is None:
                    raise ValueError(f"Spent coin {coin_id.hex()} not found")
                
                cr = CoinRecord.from_bytes(coin_blob)
                if cr.spent_block_index != 0:
                    raise ValueError(f"Coin {coin_id.hex()} already spent at height {cr.spent_block_index}")
                
                cr = CoinRecord(cr.coin, cr.confirmed_block_index, uint32(block_index),
                              cr.coinbase, cr.timestamp)
                spent_records.append(cr)
                batch.put(b"c" + coin_id, bytes(cr))
        
        # Write undo info
        undo_data = struct.pack(">Q", timestamp)  # timestamp
        undo_data += struct.pack(">I", len(new_coins))  # n_created
        for nc in new_coins:
            coin = Coin(bytes32(nc.parent), bytes32(nc.puzzle_hash), uint64(nc.amount))
            undo_data += bytes(coin.name())
        undo_data += struct.pack(">I", len(spent_coin_ids))  # n_spent
        for coin_id in spent_coin_ids:
            undo_data += coin_id
        batch.put(b"b" + struct.pack(">I", block_index), undo_data)
        
        # Update peak
        peak_data = struct.pack(">I", block_index) + block_hash
        batch.put(b"p", peak_data)
        
        self.db.write(batch)
        return spent_records
    
    def rewind_to_block(self, block_index: int) -> None:
        batch = WriteBatch()
        
        # Find all undo records above target
        prefix = b"b"
        keys_to_delete = []
        
        for key, value in self.db.items():
            if not key.startswith(prefix) or len(key) != 5:
                continue
            
            height = struct.unpack(">I", key[1:5])[0]
            if height > block_index:
                keys_to_delete.append((height, key, value))
        
        # Process in reverse order
        for height, key, undo_data in sorted(keys_to_delete, reverse=True):
            offset = 0
            timestamp = struct.unpack(">Q", undo_data[offset:offset+8])[0]
            offset += 8
            
            # Delete created coins
            n_created = struct.unpack(">I", undo_data[offset:offset+4])[0]
            offset += 4
            for _ in range(n_created):
                coin_id = undo_data[offset:offset+32]
                batch.delete(b"c" + coin_id)
                offset += 32
            
            # Unspend spent coins
            n_spent = struct.unpack(">I", undo_data[offset:offset+4])[0]
            offset += 4
            for _ in range(n_spent):
                coin_id = undo_data[offset:offset+32]
                coin_blob = self.db.get(b"c" + coin_id)
                if coin_blob:
                    cr = CoinRecord.from_bytes(coin_blob)
                    cr = CoinRecord(cr.coin, cr.confirmed_block_index, uint32(0),
                                  cr.coinbase, cr.timestamp)
                    batch.put(b"c" + coin_id, bytes(cr))
                offset += 32
            
            # Delete undo record
            batch.delete(key)
        
        # Update peak
        peak_data = struct.pack(">I", block_index) + b"\x00" * 32
        batch.put(b"p", peak_data)
        
        self.db.write(batch)
    
    def get_coin_records(self, coin_ids: list[bytes]) -> list[CoinRecord | None]:
        results = []
        for coin_id in coin_ids:
            coin_blob = self.db.get(b"c" + coin_id)
            if coin_blob is None:
                results.append(None)
            else:
                results.append(CoinRecord.from_bytes(coin_blob))
        return results
    
    def peak(self) -> tuple[int, bytes] | None:
        peak_blob = self.db.get(b"p")
        if peak_blob is None:
            return None
        height = struct.unpack(">I", peak_blob[:4])[0]
        block_hash = peak_blob[4:36]
        return (height, block_hash)
    
    def close(self) -> None:
        self.db.close()
    
    def db_size(self) -> int:
        """Estimate RocksDB size by summing SST files."""
        total = 0
        for f in self.db_path.rglob("*.sst"):
            total += f.stat().st_size
        return total
    
    def num_coins(self) -> int:
        count = 0
        for key, _ in self.db.items():
            if key.startswith(b"c"):
                count += 1
        return count


class RocksLeanStore(RocksStore):
    """
    RocksDB store with spent coins deleted.
    The undo log stores full CoinRecords for spent coins (needed for resurrection).
    """
    
    def process_spends(
        self,
        block_index: int,
        block_hash: bytes,
        timestamp: int,
        new_coins: list[NewCoin],
        spent_coin_ids: list[bytes],
    ) -> list[CoinRecord]:
        batch = WriteBatch()
        spent_records = []
        ephemeral = {}
        
        # Insert new coins
        for nc in new_coins:
            coin = Coin(bytes32(nc.parent), bytes32(nc.puzzle_hash), uint64(nc.amount))
            cr = CoinRecord(coin, uint32(block_index), uint32(0), nc.coinbase, uint64(timestamp))
            batch.put(b"c" + nc.coin_id, bytes(cr))
            ephemeral[nc.coin_id] = cr
        
        # Delete spent coins and save full records in undo
        for coin_id in spent_coin_ids:
            if coin_id in ephemeral:
                # Ephemeral: just delete it
                cr = ephemeral[coin_id]
                cr = CoinRecord(cr.coin, cr.confirmed_block_index, uint32(block_index),
                              cr.coinbase, cr.timestamp)
                spent_records.append(cr)
                batch.delete(b"c" + coin_id)
            else:
                coin_blob = self.db.get(b"c" + coin_id)
                if coin_blob is None:
                    raise ValueError(f"Spent coin {coin_id.hex()} not found")
                
                cr = CoinRecord.from_bytes(coin_blob)
                if cr.spent_block_index != 0:
                    raise ValueError(f"Coin {coin_id.hex()} already spent")
                
                # Mark as spent for undo record
                cr = CoinRecord(cr.coin, cr.confirmed_block_index, uint32(block_index),
                              cr.coinbase, cr.timestamp)
                spent_records.append(cr)
                batch.delete(b"c" + coin_id)
        
        # Write undo info with full spent records
        undo_data = struct.pack(">Q", timestamp)
        undo_data += struct.pack(">I", len(new_coins))
        for nc in new_coins:
            coin = Coin(bytes32(nc.parent), bytes32(nc.puzzle_hash), uint64(nc.amount))
            undo_data += bytes(coin.name())
        undo_data += struct.pack(">I", len(spent_records))
        for cr in spent_records:
            undo_data += bytes(cr)  # Full CoinRecord
        batch.put(b"b" + struct.pack(">I", block_index), undo_data)
        
        # Update peak
        peak_data = struct.pack(">I", block_index) + block_hash
        batch.put(b"p", peak_data)
        
        self.db.write(batch)
        return spent_records
    
    def rewind_to_block(self, block_index: int) -> None:
        batch = WriteBatch()
        
        # Find all undo records above target
        prefix = b"b"
        keys_to_delete = []
        
        for key, value in self.db.items():
            if not key.startswith(prefix) or len(key) != 5:
                continue
            
            height = struct.unpack(">I", key[1:5])[0]
            if height > block_index:
                keys_to_delete.append((height, key, value))
        
        # Process in reverse order
        for height, key, undo_data in sorted(keys_to_delete, reverse=True):
            offset = 0
            timestamp = struct.unpack(">Q", undo_data[offset:offset+8])[0]
            offset += 8
            
            # Delete created coins
            n_created = struct.unpack(">I", undo_data[offset:offset+4])[0]
            offset += 4
            for _ in range(n_created):
                coin_id = undo_data[offset:offset+32]
                batch.delete(b"c" + coin_id)
                offset += 32
            
            # Restore spent coins from full records
            n_spent = struct.unpack(">I", undo_data[offset:offset+4])[0]
            offset += 4
            for _ in range(n_spent):
                # Read full CoinRecord (89 bytes: 32+32+8+4+4+1+8)
                cr_blob = undo_data[offset:offset+89]
                cr = CoinRecord.from_bytes(cr_blob)
                coin_id = bytes(cr.coin.name())
                # Unspend it
                cr_unspent = CoinRecord(cr.coin, cr.confirmed_block_index, uint32(0),
                                      cr.coinbase, cr.timestamp)
                batch.put(b"c" + coin_id, bytes(cr_unspent))
                offset += 89
            
            # Delete undo record
            batch.delete(key)
        
        # Update peak
        peak_data = struct.pack(">I", block_index) + b"\x00" * 32
        batch.put(b"p", peak_data)
        
        self.db.write(batch)


def create_store(backend: str, db_path: Path) -> CoinStore:
    """Factory function to create a coin store."""
    if backend == "sqlite-full":
        return SqliteFullStore(db_path)
    elif backend == "sqlite-consensus":
        return SqliteConsensusStore(db_path)
    elif backend == "rocks":
        return RocksStore(db_path)
    elif backend == "rocks-lean":
        return RocksLeanStore(db_path)
    else:
        raise ValueError(f"Unknown backend: {backend}")
