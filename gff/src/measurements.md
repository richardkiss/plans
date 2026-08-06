# Measurements

Nothing here yet. No numbers exist — R1, the read-only mainnet resolver
prototype, hasn't run. This page stays honestly empty until it does.

## Pending: R1, the read-only resolver prototype

R1 peers into transaction gossip (or polls a local node's mempool RPC),
detects FF-eligible singleton spends (`supports_fast_forward` is already
exported to Python — `wheel/src/api.rs:415,805`), tracks singleton
movement, and measures. Zero blast radius: it's read-only; rollback is
stopping the process.

What it will measure:

- **FF traffic volume** — how many FF-eligible spends mainnet actually
  carries, and which products emit them. (Pool-protocol plot-NFT spends
  carry `AGG_SIG_ME` and are *not* eligible; what the real traffic is, I
  don't know.)
- **Born-stale frequency** — how often spends arrive after their singleton
  already moved on-chain. These are the spends only the annex can save
  post-GFF, so this number sizes how much the annex matters.
- **Node-FF firing rate** — how often confirmed blocks contain rebased
  parents differing from the gossiped originals. Direct on-chain evidence
  of whether in-node fast forward is load-bearing on mainnet at all today.
- **Resolver coverage** (once R2 runs) — the fraction of observed FF
  traffic a resolver handles, which is the gate condition for removing
  node-FF ([pathway](pathway.md), N2 → N3).

These numbers decide how much of the transition needs care versus is
theoretical. I'm not going to guess them.
