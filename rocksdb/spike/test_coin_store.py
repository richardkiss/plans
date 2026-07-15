#!/usr/bin/env python3
"""Unit tests for coin store backends."""
import hashlib
import tempfile
from pathlib import Path

import pytest

from coin_store import NewCoin, create_store


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def make_coin_id(*parts) -> bytes:
    """Generate a deterministic value for test purposes."""
    return hashlib.sha256(b"".join(str(p).encode() for p in parts)).digest()


def make_new_coin(parent_seed, puzzle_seed, amount, coinbase=False) -> NewCoin:
    """Create a NewCoin with properly computed coin_id."""
    from chia_rs import Coin
    from chia_rs.sized_bytes import bytes32
    from chia_rs.sized_ints import uint64
    
    parent = make_coin_id(parent_seed)
    puzzle_hash = make_coin_id(puzzle_seed)
    coin = Coin(bytes32(parent), bytes32(puzzle_hash), uint64(amount))
    coin_id = bytes(coin.name())
    
    return NewCoin(
        coin_id=coin_id,
        parent=parent,
        puzzle_hash=puzzle_hash,
        amount=amount,
        coinbase=coinbase,
    )


@pytest.mark.parametrize("backend", ["sqlite-full", "sqlite-consensus", "rocks", "rocks-lean"])
def test_basic_process_and_query(backend, temp_dir):
    """Test basic coin creation and querying."""
    store = create_store(backend, temp_dir / backend)
    
    # Create some coins
    coins = [
        make_new_coin(f"parent-{i}", f"puzzle-{i}", 1000 * i)
        for i in range(5)
    ]
    
    block_hash = make_coin_id("block", 1)
    spent = store.process_spends(1, block_hash, 1000, coins, [])
    
    assert len(spent) == 0  # No spends yet
    assert store.peak() == (1, block_hash)
    
    # Query coins
    records = store.get_coin_records([c.coin_id for c in coins])
    assert all(r is not None for r in records)
    assert all(r.confirmed_block_index == 1 for r in records)
    assert all(r.spent_block_index == 0 for r in records)
    
    store.close()


@pytest.mark.parametrize("backend", ["sqlite-full", "sqlite-consensus", "rocks", "rocks-lean"])
def test_spend_coins(backend, temp_dir):
    """Test spending coins."""
    store = create_store(backend, temp_dir / backend)
    
    # Block 1: Create coins
    coins = [
        make_new_coin(f"parent-{i}", f"puzzle-{i}", 1000 * i)
        for i in range(5)
    ]
    store.process_spends(1, make_coin_id("block", 1), 1000, coins, [])
    
    # Block 2: Spend first two coins
    spent_ids = [coins[0].coin_id, coins[1].coin_id]
    spent = store.process_spends(2, make_coin_id("block", 2), 2000, [], spent_ids)
    
    assert len(spent) == 2
    assert all(r.spent_block_index == 2 for r in spent)
    
    # Verify
    records = store.get_coin_records(spent_ids)
    for r in records:
        if backend in ["sqlite-full", "sqlite-consensus", "rocks"]:
            # These keep spent coins
            assert r is not None
            assert r.spent_block_index == 2
        else:
            # rocks-lean deletes spent coins
            assert r is None
    
    # Unspent coins still there
    unspent_ids = [coins[2].coin_id, coins[3].coin_id]
    records = store.get_coin_records(unspent_ids)
    assert all(r is not None for r in records)
    assert all(r.spent_block_index == 0 for r in records)
    
    store.close()


@pytest.mark.parametrize("backend", ["sqlite-full", "sqlite-consensus", "rocks", "rocks-lean"])
def test_ephemeral_coins(backend, temp_dir):
    """Test coins created and spent in the same block."""
    store = create_store(backend, temp_dir / backend)
    
    # Create and spend in same block
    coins = [
        make_new_coin(f"parent-{i}", f"puzzle-{i}", 1000 * i)
        for i in range(3)
    ]
    
    # Spend coin 0 and 1 in same block they're created
    spent_ids = [coins[0].coin_id, coins[1].coin_id]
    spent = store.process_spends(1, make_coin_id("block", 1), 1000, coins, spent_ids)
    
    assert len(spent) == 2
    assert all(r.confirmed_block_index == 1 for r in spent)
    assert all(r.spent_block_index == 1 for r in spent)
    
    store.close()


@pytest.mark.parametrize("backend", ["sqlite-full", "sqlite-consensus", "rocks", "rocks-lean"])
def test_rewind(backend, temp_dir):
    """Test rewinding blocks."""
    store = create_store(backend, temp_dir / backend)
    
    # Block 1: Create 5 coins
    coins1 = [
        make_new_coin(f"parent-1-{i}", f"puzzle-1-{i}", 1000 * i)
        for i in range(5)
    ]
    store.process_spends(1, make_coin_id("block", 1), 1000, coins1, [])
    
    # Block 2: Spend 2 coins, create 3 new
    spent_ids = [coins1[0].coin_id, coins1[1].coin_id]
    coins2 = [
        make_new_coin(f"parent-2-{i}", f"puzzle-2-{i}", 2000 * i)
        for i in range(3)
    ]
    store.process_spends(2, make_coin_id("block", 2), 2000, coins2, spent_ids)
    
    # Block 3: Spend 1 more
    spent_ids_3 = [coins1[2].coin_id]
    store.process_spends(3, make_coin_id("block", 3), 3000, [], spent_ids_3)
    
    assert store.peak()[0] == 3
    
    # Rewind to block 1
    store.rewind_to_block(1)
    
    assert store.peak()[0] == 1
    
    # Verify: coins from block 1 exist and unspent
    records = store.get_coin_records([c.coin_id for c in coins1])
    assert all(r is not None for r in records)
    assert all(r.spent_block_index == 0 for r in records)
    
    # Coins from block 2 should be gone
    records = store.get_coin_records([c.coin_id for c in coins2])
    assert all(r is None for r in records)
    
    store.close()


@pytest.mark.parametrize("backend", ["sqlite-full", "sqlite-consensus", "rocks", "rocks-lean"])
def test_double_spend_detection(backend, temp_dir):
    """Test that double spends are detected."""
    store = create_store(backend, temp_dir / backend)
    
    # Create coin
    coin = make_new_coin("parent-0", "puzzle-0", 1000)
    store.process_spends(1, make_coin_id("block", 1), 1000, [coin], [])
    
    # Spend it
    store.process_spends(2, make_coin_id("block", 2), 2000, [], [coin.coin_id])
    
    # Try to spend again - should raise
    with pytest.raises(ValueError, match="already spent|not found"):
        store.process_spends(3, make_coin_id("block", 3), 3000, [], [coin.coin_id])
    
    store.close()


def main():
    raise SystemExit(pytest.main([__file__, "-v"]))


if __name__ == "__main__":
    main()
