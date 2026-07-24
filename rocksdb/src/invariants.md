# Atomicity invariants

The migration ends with the peak and the chain index living inside the coin
store's write scope, and with `DBWrapper2` — the shared transaction layer
above the stores — reduced to an implementation detail. Two earlier attempts
in this direction (#19799, #19949) stalled in review on one question: today
`BlockStore` and `CoinStore` rely on sharing a database, and their updates
land in the same transaction — if we step away from that, what keeps them in
sync?

Fair question, and it deserves a written answer rather than a promise in a
PR thread. This page is that answer: an audit of every write-transaction
site in the node, what the shared transaction actually protects, and why the
target design keeps that guarantee without a cross-store transaction.
Verified against main at `54201dc53` (2026-07-21). Later PRs cite this page
instead of re-arguing atomicity from scratch.

## Every write transaction in the node

One `DBWrapper2` instance serves the whole blockchain DB: `FullNode.manage()`
creates it (`full_node.py:253`) and hands it to `BlockStore`, `HintStore`,
and `CoinStore` (`full_node.py:277-279`), plus `BlockHeightMap`
(`full_node.py:301`). `BlockStore.transaction()` is literally
`return self.db_wrapper.writer()` (`block_store.py:195`).

Here is every site that opens a write transaction or reaches for the
transaction layer at all. (Store methods themselves all use
`writer_maybe_transaction()`, which joins whatever transaction is open —
that's the mechanism, not a separate site.)

| Site | Mechanism | Stores written | Cross-store? |
|---|---|---|---|
| `Blockchain.add_block` → `_reconsider_peak` (`blockchain.py:436`) | `block_store.transaction()` | BlockStore: `add_full_block` :438, `rollback` :614, `set_in_chain` :615, `set_peak` :618. CoinStore: `rollback_to_block` :533, `new_block` :595 | **yes — the only one in production code** |
| `FullNodeSimulator.revert_block_height` (`full_node_simulator.py:170`) | `block_store.transaction()` | CoinStore: `rollback_to_block` :172. BlockStore: `rollback` :174, `set_peak` :175 | yes — simulator/test infrastructure; same invariant as above, needs the same replacement API |
| Hint writes after a new peak (`full_node.py:1479` and `:1982`) | `HintStore.add_hints` → its own `writer_maybe_transaction` | HintStore | no — and it runs *after* the peak transaction commits |
| Weight-proof segment persistence (`weight_proof.py:173,249,299` → `block_store.py:164`) | store-internal `writer_maybe_transaction` | BlockStore (`sub_epoch_segments_v3`) | no — background, standalone |
| Compactification (`full_node.py:3266`) | `db_wrapper.writer()` called directly by `FullNode`, wrapping `replace_proof` | BlockStore | no — single-store, though the call sits above the store layer and should move behind a `BlockStore` method |
| DB-version bootstrap (`full_node.py:268`) | `writer_maybe_transaction` | the `database_version` table | no — pre-store setup |

That's the complete list. The mempool is in-memory (its own SQLite, not
`DBWrapper2`); the wallet and data layer have their own databases and their
own wrapper instances; harvester and plotting code never touch the
blockchain DB.

So the invariant the shared transaction protects is exactly one: **the coin
set, the `in_main_chain` flags, and the peak pointer move together or not at
all.** Nothing else in the node spans stores in a write transaction.

## Hints are already outside it

Hints are written by `FullNode` after `add_block` returns — after the peak
transaction has committed (`full_node.py:1479`, `:1982`). A crash between
the commit and `add_hints` loses those hints today, and nothing breaks:
they're derived data, rebuildable from the blocks. Explorer-side data being
non-atomic with consensus is the status quo, not something the migration
introduces.

## Cross-store reads are already unsynchronized

The node uses `DBWrapper2.reader()` — the consistent-snapshot read — exactly
once above the store layer: `full_node_api.py:2195`, the wallet-protocol
mempool-updates path (which also reads the `hints` table with raw SQL,
bypassing `HintStore`). One more lives inside `CoinStore` itself
(`batch_coin_states_by_puzzle_hashes`, `coin_store.py:478`), single-store.
Every other read in the node is `reader_no_transaction()`: a pooled
connection, no snapshot, no consistency across calls.

The peer and RPC handlers cope with this by hand. The idiom: read some
blocks, then check `height_to_hash(height)` still returns the hash you
expect, and bail if a reorg moved it mid-read. It appears at
`full_node_api.py:1417`, `:1432`, `:1501`, `:1515` and
`full_node_rpc_api.py:433`, `:913`; the coin- and puzzle-subscription
handlers (`full_node_api.py:2045`, `:2126`) are the same family, checking a
client-supplied previous hash. Weight-proof generation walks thousands of
heights interleaved with awaits and doesn't even do the re-check — a reorg
mid-walk produces an inconsistent proof, tolerated in practice.

The point: there is no cross-store read consistency today to lose. The
migration *adds* it — `snapshot()` on the coin store and peak-pinned
`view(peak)` reads — and the hand-rolled re-check boilerplate gets deleted
once its callers move over.

## Why no cross-store transaction remains

The one protected invariant is coin set + chain flags + peak. That is
precisely the state the [target design](target.md) fuses into the consensus
store: peak and the chain index (today the `in_main_chain` flags, eventually
an explicit `height → header_hash` map) move into the coin store's write
scope, so `new_block` and `rollback_to_block` update coins, chain index, and
peak in one single-store write. The block blob write moves ahead of the
consensus commit — a crash in between leaves an orphaned blob, which is
harmless and re-fetchable.

After that step there is no cross-store write transaction anywhere in the
node — not because a wrapper hides it, but because none is needed. The
atomic unit is the consensus store itself. This is why the design has no
facade over the three stores: a wrapper that delegates its transactions back
to `DBWrapper2` keeps the coupling and abstracts nothing, which is the shape
that failed review twice (#19949, #20566). The simulator's
`revert_block_height` switches to the same public rewind API instead of
reaching into two stores.

## What per-store write scopes actually need

`DBWrapper2`'s write API does more than the node uses. From the call sites
above, the full contract in use is:

- `writer()` (`db_wrapper.py:362`) — the outer commit scope. Commit happens
  on outermost exit.
- `writer_maybe_transaction()` (`:439`) — join the ambient transaction if
  one is open, else be your own. Every store method uses this internally;
  it's how store calls silently become atomic inside `add_block`'s scope.

Nested `writer()` scopes become SAVEPOINTs (`:318`), which would let an
inner scope roll back while the outer transaction continues. No node code
path uses that: no inner scope intentionally fails and continues. So the
replacement contract for a per-store write ACM is an outer commit scope plus
auto-join for store methods — two levels, no partial rollback. A RocksDB
backend satisfies this with one `WriteBatch` per outer scope, since store
methods only ever need "join the ambient batch". On the read side,
`reader()` maps to a snapshot and `reader_no_transaction()` to plain point
reads.

I'm stating the SAVEPOINT non-use explicitly because it's a fair thing to
ask about: partial rollback is a real SQLite feature and the per-store ACMs
drop it. The audit says nothing depends on it. If something ever does, it
would have to be new code, written against the new interface, which can
decide then whether it needs an inner scope.
