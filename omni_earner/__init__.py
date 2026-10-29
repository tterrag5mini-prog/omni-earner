"""Omni-Earner: Dual-Vector Autonomous Agent Package."""

from typing import Any

from omni_earner.config import Settings, get_settings
from omni_earner.ledger import CircuitBreakerError, TreasuryLedger
from omni_earner.router import TieredModelRouter, TriageResult
from omni_earner.sandbox import IsolatedSandbox
from omni_earner.scraper import BountyTask, GitHubBountyScraper, extract_bounty_usd
from omni_earner.x402_oracle import X402OracleService

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "get_settings",
    "CircuitBreakerError",
    "TreasuryLedger",
    "BountyTask",
    "GitHubBountyScraper",
    "extract_bounty_usd",
    "TieredModelRouter",
    "TriageResult",
    "IsolatedSandbox",
    "X402OracleService",
    "Orchestrator",
]


def __getattr__(name: str) -> Any:
    if name == "Orchestrator":
        from omni_earner.orchestrator import Orchestrator

        return Orchestrator
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
