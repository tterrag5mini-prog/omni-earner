"""Configuration and environment settings for Omni-Earner."""

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    """Runtime configuration settings loaded from environment with safe defaults."""

    DB_PATH: str = field(
        default_factory=lambda: os.getenv("OE_DB_PATH", "treasury.db")
    )
    OUTBOX_DIR: str = field(
        default_factory=lambda: os.getenv("OE_OUTBOX_DIR", "outbox")
    )
    STARTING_BALANCE_USD: float = field(
        default_factory=lambda: float(os.getenv("OE_STARTING_BALANCE", "25.00"))
    )
    MAX_COST_PER_TASK_USD: float = field(
        default_factory=lambda: float(os.getenv("OE_MAX_TASK_COST", "2.00"))
    )
    MIN_EV_MULTIPLIER: float = field(
        default_factory=lambda: float(os.getenv("OE_MIN_EV_MULT", "3.0"))
    )
    TARGET_MARGIN: float = field(
        default_factory=lambda: float(os.getenv("OE_TARGET_MARGIN", "0.50"))
    )
    OWNER_SWEEP_RATIO: float = field(
        default_factory=lambda: float(os.getenv("OE_OWNER_SWEEP_RATIO", "0.70"))
    )
    PAYOUT_WALLET: str = field(
        default_factory=lambda: os.getenv(
            "OE_PAYOUT_WALLET", "0x71C8F27B9eC568f86C20a59a9DeD4984A0be889A"
        )
    )
    USDC_CONTRACT_BASE: str = field(
        default_factory=lambda: os.getenv(
            "OE_USDC_CONTRACT_BASE",
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        )
    )
    X402_PRICE_USD: float = field(
        default_factory=lambda: float(os.getenv("OE_X402_PRICE_USD", "0.05"))
    )
    SHADOW_MODE: bool = field(
        default_factory=lambda: os.getenv("OE_SHADOW_MODE", "true").lower()
        == "true"
    )
    LLM_API_KEY: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )


def get_settings() -> Settings:
    """Instantiate and return the current runtime settings."""
    return Settings()
