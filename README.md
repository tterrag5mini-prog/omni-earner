# Omni-Earner: Dual-Vector Autonomous Monetization Agent

[![Test Suite](https://img.shields.io/badge/pytest-26%20passed%20100%25-brightgreen)](tests/test_full_system.py)
[![Network](https://img.shields.io/badge/Network-Base%20(eip155%3A8453)-blue)](https://basescan.org)
[![Settlement](https://img.shields.io/badge/Asset-USDC%20(0x8335...)-blue)](https://basescan.org/token/0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

`omni_earner` is a self-sustaining autonomous monetization agent governed by a SQLite Survival Ledger. It operates two concurrent monetization vectors:

1. **Active Vector (Outbound Bounty Hunter):**
   - Discovers open GitHub issues with Algora/Opire bounty labels.
   - Evaluates tasks against deterministic Expected Value (EV) and Maximum Allowable Inference Cost (MAIC) survival gates.
   - Triages issues via a tiered routing model ($0.002 fast triage, $0.45 frontier solve).
   - Clones target repositories into an isolated local git sandbox, applies unified diff patches, and verifies that `pytest` passes with exit code 0.
   - Generates production-ready `/claim` PR bundles in `./outbox/`.

2. **Passive Vector (Inbound HTTP x402 A2A Micro-Oracle):**
   - Implements the HTTP 402 Payment Required specification on Base (`eip155:8453`) USDC.
   - Challenges unauthenticated incoming agent requests with HTTP 402 and structured settlement metadata ($0.05 USDC).
   - Verifies incoming cryptographic `X-PAYMENT` receipts, deducts micro-inference compute costs, and credits structured repository/issue alpha.
   - **Live Public Endpoint:** `https://likewise-dedicated-possession-rest.trycloudflare.com`

3. **Survival Ledger & Circuit Breaker:**
   - 70% of gross revenue is swept to the owner cold wallet (`OWNER_SWEEP_RATIO = 0.70` to `0x71C8F27B9eC568f86C20a59a9DeD4984A0be889A`).
   - 30% of gross revenue is retained in the agent treasury for operational compute.
   - Enforces strict per-task spending limits and balance limits via `CircuitBreakerError`.

---

## 🌐 Live Micro-Oracle Endpoints

The x402 Micro-Oracle is running live over the internet:

- **Health Check:** `https://likewise-dedicated-possession-rest.trycloudflare.com/health`
- **Audit Ledger:** `https://likewise-dedicated-possession-rest.trycloudflare.com/ledger`
- **Monetized Alpha API:** `https://likewise-dedicated-possession-rest.trycloudflare.com/alpha/bounties`

### Querying the Oracle (A2A Protocol)

#### Step 1: Issue Unauthenticated Request
```bash
curl -i https://likewise-dedicated-possession-rest.trycloudflare.com/alpha/bounties
```
**Response (HTTP 402 Payment Required):**
```json
{
  "status": 402,
  "protocol": "x402",
  "scheme": "exact",
  "network": "eip155:8453",
  "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  "payTo": "0x71C8F27B9eC568f86C20a59a9DeD4984A0be889A",
  "amountUSD": 0.05,
  "description": "Pay $0.05 USDC on Base to unlock structured bounty & repo alpha"
}
```

#### Step 2: Retry with Base Payment Receipt
```bash
curl -H "X-PAYMENT: x402-sig-0x123..." https://likewise-dedicated-possession-rest.trycloudflare.com/alpha/bounties
```
**Response (HTTP 200 OK):**
```json
{
  "status": 200,
  "protocol": "x402",
  "network": "eip155:8453",
  "receipt": "x402-sig-0x123...",
  "settlement": {
    "gross_usd": 0.05,
    "owner_swept_usd": 0.035,
    "agent_retained_usd": 0.015
  },
  "data": {
    "alpha_type": "bounty_intelligence",
    "top_bounties": [...]
  }
}
```

---

## 🛠 Local Setup & Verification

```bash
# Initialize virtualenv and dependencies
python3 -m venv .venv
.venv/bin/pip install -e .

# Run test suite (26 tests)
.venv/bin/python -m pytest -v

# Run the end-to-end verification pipeline
.venv/bin/omni-earner --auto-verify

# Run the autonomous earner targeting $1.00 net profit
.venv/bin/omni-worker --target 1.00
```
