# Omni-Earner: Dual-Vector Autonomous Monetization Agent

`omni_earner` is a self-sustaining autonomous monetization agent governed by a SQLite Survival Ledger. It operates two concurrent monetization vectors:

1. **Active Vector (Outbound Bounty Hunter):**
   - Discovers open GitHub issues with Algora/Opire bounty labels.
   - Evaluates tasks against deterministic Expected Value (EV) and Maximum Allowable Inference Cost (MAIC) survival gates.
   - Triages issues via a tiered routing model.
   - Clones target repositories into an isolated local git sandbox, applies unified diff patches, and verifies that `pytest` passes with exit code 0.
   - Generates production-ready `/claim` PR bundles in `./outbox/`.

2. **Passive Vector (Inbound HTTP x402 A2A Micro-Oracle):**
   - Implements the HTTP 402 Payment Required specification on Base (`eip155:8453`) USDC.
   - Challenges unauthenticated incoming agent requests with HTTP 402 and structured settlement metadata.
   - Verifies incoming cryptographic `X-PAYMENT` receipts, deducts micro-inference compute costs, and credits structured repository/issue alpha.

3. **Survival Ledger & Circuit Breaker:**
   - 70% of gross revenue is swept to the owner cold wallet (`OWNER_SWEEP_RATIO = 0.70`).
   - 30% of gross revenue is retained in the agent treasury for operational compute.
   - Enforces strict per-task spending limits and balance limits via `CircuitBreakerError`.
