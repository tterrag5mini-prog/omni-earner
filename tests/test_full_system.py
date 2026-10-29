"""Comprehensive test suite for Omni-Earner dual-vector monetization agent."""

import os
import tempfile
import pytest
import httpx

from omni_earner.config import Settings
from omni_earner.ledger import CircuitBreakerError, TreasuryLedger
from omni_earner.orchestrator import Orchestrator
from omni_earner.router import TieredModelRouter, TriageResult
from omni_earner.sandbox import IsolatedSandbox
from omni_earner.scraper import BountyTask, GitHubBountyScraper, extract_bounty_usd
from omni_earner.x402_oracle import X402OracleService


# ==============================================================================
# 1. REGEX BOUNTY EXTRACTION TESTS
# ==============================================================================


@pytest.mark.parametrize(
    "text,labels,expected",
    [
        ("Fix this bug for $100", [], 100.0),
        ("Urgent issue paying $1,200 on completion", [], 1200.0),
        ("Offering 250 USD to the solver", [], 250.0),
        ("Algora reward: 500 USDC on Base", [], 500.0),
        ("Run /bounty $300 to fund this", [], 300.0),
        ("Issue created. /bounty $500", [], 500.0),
        ("Algora bounty: 💎 $100", [], 100.0),
        ("Label in issue", ["💎 $150", "bug"], 150.0),
        ("Multiple amounts: $50 first, then updated to /bounty $450", [], 450.0),
        ("No bounty here, just a standard issue", ["good-first-issue"], 0.0),
    ],
)
def test_extract_bounty_usd(text: str, labels: list[str], expected: float) -> None:
    """Verify regex correctly parses various currency and bounty formats."""
    result = extract_bounty_usd(text, labels)
    assert result == expected


# ==============================================================================
# 2. TREASURY LEDGER & SURVIVAL CIRCUIT BREAKER TESTS
# ==============================================================================


def test_ledger_genesis_and_balance() -> None:
    """Verify genesis initialization and balance tracking."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(db_path=tmp.name, starting_balance=50.0)
        assert ledger.get_balance() == 50.0
        txs = ledger.get_transactions()
        assert len(txs) == 1
        assert txs[0]["kind"] == "GENESIS"
        assert txs[0]["amount_usd"] == 50.0


def test_ledger_maic_calculation() -> None:
    """Verify MAIC math: Bounty * Win_Prob * (1 - Margin)."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(
            db_path=tmp.name,
            starting_balance=25.0,
            target_margin=0.5,
        )
        # Bounty $200, Win Prob 0.85, Margin 0.50 -> 200 * 0.85 * 0.5 = 85.0
        maic = ledger.calculate_maic(bounty_usd=200.0, win_prob=0.85)
        assert maic == 85.0

        # Bounty $15, Win Prob 0.05, Margin 0.50 -> 15 * 0.05 * 0.5 = 0.375
        maic_noise = ledger.calculate_maic(bounty_usd=15.0, win_prob=0.05)
        assert maic_noise == 0.375


def test_ledger_can_execute_gates() -> None:
    """Test the deterministic 4-part Survival Gate."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(
            db_path=tmp.name,
            starting_balance=25.0,
            max_cost_per_task=2.0,
            min_ev_multiplier=3.0,
            target_margin=0.5,
        )

        # High-EV task passes
        assert ledger.can_execute(
            estimated_cost=0.45, bounty_usd=200.0, win_prob=0.85
        ) is True

        # Low-EV task fails MAIC gate (0.45 > 0.375) and EV gate (0.75 < 1.35)
        assert ledger.can_execute(
            estimated_cost=0.45, bounty_usd=15.0, win_prob=0.05
        ) is False

        # Task exceeding hard budget ($2.50 > $2.00) fails
        assert ledger.can_execute(
            estimated_cost=2.50, bounty_usd=500.0, win_prob=0.90
        ) is False

        # Insolvent check: cost exceeds treasury balance
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp_poor:
            ledger_poor = TreasuryLedger(
                db_path=tmp_poor.name, starting_balance=0.10
            )
            assert ledger_poor.can_execute(
                estimated_cost=0.45, bounty_usd=200.0, win_prob=0.85
            ) is False


def test_circuit_breaker_tripping_on_task_cap() -> None:
    """Verify CircuitBreakerError is raised when task expenditure cap is violated."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(
            db_path=tmp.name,
            starting_balance=25.0,
            max_cost_per_task=2.0,
        )
        # Debit $1.50
        bal1 = ledger.record_debit("task-1", 1.50, "DEBIT_COMPUTE")
        assert bal1 == 23.50

        # Attempting to debit $0.60 on task-1 would reach $2.10 > $2.00 cap -> Tripped!
        with pytest.raises(CircuitBreakerError, match="Circuit breaker tripped"):
            ledger.record_debit("task-1", 0.60, "DEBIT_COMPUTE")


def test_circuit_breaker_tripping_on_insolvency() -> None:
    """Verify CircuitBreakerError is raised if treasury balance would drop below 0."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(
            db_path=tmp.name,
            starting_balance=1.0,
            max_cost_per_task=5.0,
        )
        # Attempt to debit $1.50 when balance is $1.00
        with pytest.raises(CircuitBreakerError, match="Insufficient treasury balance"):
            ledger.record_debit("task-2", 1.50, "DEBIT_COMPUTE")


def test_revenue_sweep_70_30_allocation() -> None:
    """Verify 70% sweep to cold wallet and 30% retention to operational treasury."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(
            db_path=tmp.name,
            starting_balance=20.0,
            owner_sweep_ratio=0.70,
        )
        # Record $100 revenue
        res = ledger.record_revenue("task-rev-1", 100.0, "CREDIT_REVENUE")
        assert res["gross"] == 100.0
        assert res["swept"] == 70.0
        assert res["retained"] == 30.0
        assert res["new_balance"] == 50.0  # 20.0 starting + 30.0 retained

        # Verify summary report math
        summary = ledger.summary_report()
        assert summary["total_gross_revenue"] == 100.0
        assert summary["total_swept_to_owner"] == 70.0
        assert summary["agent_retained_revenue"] == 30.0
        assert summary["current_balance"] == 50.0
        assert summary["net_agent_profit"] == 30.0
        assert summary["roi_percent"] == 150.0  # (30 / 20) * 100


# ==============================================================================
# 3. SCRAPER & SYNTHETIC DATA TESTS
# ==============================================================================


def test_synthetic_bounties_generation() -> None:
    """Verify the 3 characteristic synthetic bounty tasks are generated correctly."""
    scraper = GitHubBountyScraper()
    bounties = scraper.generate_synthetic_bounties()
    assert len(bounties) == 3

    # Task 1: High EV
    assert bounties[0].task_id == "bounty-task-101"
    assert bounties[0].bounty_usd == 200.0
    assert "calc.py" in bounties[0].body

    # Task 2: Low EV noise
    assert bounties[1].task_id == "bounty-task-102"
    assert bounties[1].bounty_usd == 15.0

    # Task 3: Architectural rewrite trap
    assert bounties[2].task_id == "bounty-task-103"
    assert bounties[2].bounty_usd == 500.0
    assert "rewrite" in bounties[2].title.lower()


# ==============================================================================
# 4. ROUTER TRIAGE & SOLVE TESTS
# ==============================================================================


def test_router_triage_rules() -> None:
    """Verify Tier-1 triage correctly categorizes tasks."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(db_path=tmp.name, starting_balance=25.0)
        router = TieredModelRouter(ledger=ledger)
        scraper = GitHubBountyScraper()
        bounties = scraper.generate_synthetic_bounties()

        # High-EV bug
        res1 = router.triage_task(bounties[0])
        assert res1.solvable is True
        assert res1.win_prob == 0.85
        assert res1.target_file == "calc.py"

        # Low-EV noise
        res2 = router.triage_task(bounties[1])
        assert res2.solvable is True
        assert res2.win_prob == 0.05

        # Trap architectural rewrite
        res3 = router.triage_task(bounties[2])
        assert res3.solvable is False
        assert res3.win_prob == 0.01


def test_router_patch_generation() -> None:
    """Verify deterministic solve patch corrects ZeroDivisionError in calc.py."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(db_path=tmp.name, starting_balance=25.0)
        router = TieredModelRouter(ledger=ledger)
        task = BountyTask(
            task_id="test-task",
            repo="octo/calc",
            issue_num=1,
            title="Fix ZeroDivisionError in calculate_average",
            body="calc.py raises ZeroDivisionError",
            url="",
            bounty_usd=200.0,
        )

        buggy_code = (
            "def calculate_average(numbers: list[float]) -> float:\n"
            "    return sum(numbers) / len(numbers)\n"
        )

        fixed_code = router.generate_patch(
            task=task,
            file_path="calc.py",
            current_code=buggy_code,
            test_error="ZeroDivisionError",
            win_prob=0.85,
        )

        assert "if not numbers:" in fixed_code
        assert "return 0.0" in fixed_code


# ==============================================================================
# 5. SANDBOX & PYTEST VERIFICATION TESTS
# ==============================================================================


def test_sandbox_end_to_end_verification() -> None:
    """Verify Git initialization, baseline test failure, fix application, and diff capture."""
    sandbox = IsolatedSandbox()

    buggy_code = (
        "def calculate_average(numbers: list[float]) -> float:\n"
        "    return sum(numbers) / len(numbers)\n"
    )
    test_code = (
        "from calc import calculate_average\n\n"
        "def test_calculate_average():\n"
        "    assert calculate_average([2.0, 4.0]) == 3.0\n"
        "    assert calculate_average([]) == 0.0\n"
    )

    workspace = sandbox.create_mock_repo(
        buggy_code=buggy_code,
        test_code=test_code,
        filename="calc.py",
        test_filename="test_calc.py",
    )

    # 1. Verify baseline test fails
    baseline_passed, baseline_out = sandbox.run_tests(workspace)
    assert baseline_passed is False
    assert "ZeroDivisionError" in baseline_out or "FAILED" in baseline_out

    # 2. Apply fix
    fixed_code = (
        "def calculate_average(numbers: list[float]) -> float:\n"
        "    if not numbers:\n"
        "        return 0.0\n"
        "    return sum(numbers) / len(numbers)\n"
    )

    passed, unified_diff, verify_out = sandbox.apply_fix_and_verify(
        workspace_dir=workspace,
        target_file="calc.py",
        fixed_code=fixed_code,
    )

    assert passed is True
    assert "PASSED" in verify_out or "1 passed" in verify_out
    assert "+    if not numbers:" in unified_diff
    assert "+        return 0.0" in unified_diff

    sandbox.cleanup()


# ==============================================================================
# 6. x402 MICRO-ORACLE TESTS
# ==============================================================================


def test_x402_oracle_unauthenticated_challenge() -> None:
    """Verify 402 Payment Required challenge when X-PAYMENT header is absent."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(db_path=tmp.name, starting_balance=25.0)
        oracle = X402OracleService(ledger=ledger)

        status, headers, body = oracle.handle_request(headers={})
        assert status == 402
        assert headers["PAYMENT-REQUIRED"] == "x402/1.0"
        assert body["status"] == 402
        assert body["protocol"] == "x402"
        assert body["network"] == "eip155:8453"
        assert body["amountUSD"] == 0.05
        assert "USDC" in body["description"]


def test_x402_oracle_valid_payment_settlement() -> None:
    """Verify 200 OK fulfillment and ledger credit when valid receipt is provided."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(db_path=tmp.name, starting_balance=25.0)
        oracle = X402OracleService(ledger=ledger)

        initial_balance = ledger.get_balance()
        valid_receipt = "x402-sig-0x89f81a7b8e192c4b82d921e5f8832a884"

        status, headers, body = oracle.handle_request(
            headers={"X-PAYMENT": valid_receipt}
        )

        assert status == 200
        assert headers["X-PAYMENT-RESPONSE"] == "settled:eip155:8453"
        assert body["receipt"] == valid_receipt
        assert body["data"]["alpha_type"] == "bounty_intelligence"

        # Check ledger side-effects:
        # Micro-inference debit $0.001, gross revenue $0.05, 70% swept ($0.035), 30% retained ($0.015)
        # Net change = +0.015 - 0.001 = +0.014
        expected_balance = round(initial_balance + 0.015 - 0.001, 4)
        assert ledger.get_balance() == expected_balance


@pytest.mark.asyncio
async def test_x402_oracle_asgi_interface() -> None:
    """Verify the ASGI application handler with httpx.AsyncClient."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        ledger = TreasuryLedger(db_path=tmp.name, starting_balance=25.0)
        oracle = X402OracleService(ledger=ledger)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=oracle), base_url="http://test"
        ) as client:
            # 1. Unauthenticated request
            resp_402 = await client.get("/alpha/bounties")
            assert resp_402.status_code == 402
            assert resp_402.headers["payment-required"] == "x402/1.0"
            data_402 = resp_402.json()
            assert data_402["network"] == "eip155:8453"

            # 2. Authenticated request with cryptographic receipt
            resp_200 = await client.get(
                "/alpha/bounties",
                headers={"X-PAYMENT": "x402-sig-valid-usdc-token-8453"},
            )
            assert resp_200.status_code == 200
            data_200 = resp_200.json()
            assert data_200["status"] == 200
            assert "data" in data_200


# ==============================================================================
# 7. END-TO-END ORCHESTRATOR INTEGRATION TEST
# ==============================================================================


def test_orchestrator_auto_verify_pipeline() -> None:
    """Verify complete orchestrator run: triage, MAIC filter, sandbox solve, and settlement."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_treasury.db")
        outbox_dir = os.path.join(temp_dir, "test_outbox")

        settings = Settings(
            DB_PATH=db_path,
            OUTBOX_DIR=outbox_dir,
            STARTING_BALANCE_USD=25.0,
            SHADOW_MODE=True,
        )

        orchestrator = Orchestrator(settings=settings)
        active_results = orchestrator.run_active_pipeline(auto_settle=True)
        oracle_results = orchestrator.run_passive_oracle_simulation()

        # Check Active Vector Results
        assert len(active_results) == 3

        # Task 1: Solved and verified
        task1 = active_results[0]
        assert task1["task_id"] == "bounty-task-101"
        assert task1["status"] == "SOLVED_AND_VERIFIED"
        assert os.path.exists(task1["diff_path"])
        assert os.path.exists(task1["claim_path"])
        with open(task1["claim_path"], "r", encoding="utf-8") as f:
            claim_text = f.read()
            assert "/claim #101" in claim_text
            assert settings.PAYOUT_WALLET in claim_text

        # Task 2: Rejected by MAIC Survival Gate
        task2 = active_results[1]
        assert task2["task_id"] == "bounty-task-102"
        assert task2["status"] == "REJECTED_BY_MAIC_SURVIVAL_GATE"

        # Task 3: Rejected by Triage Gate
        task3 = active_results[2]
        assert task3["task_id"] == "bounty-task-103"
        assert task3["status"] == "REJECTED_BY_TRIAGE"

        # Check Passive Vector Results
        assert oracle_results["unauthenticated_status"] == 402
        assert oracle_results["authenticated_status"] == 200

        # Check Final Financial Summary
        summary = orchestrator.ledger.summary_report()
        assert summary["total_gross_revenue"] > 200.0  # 200.0 bounty + 0.05 oracle
        assert summary["total_swept_to_owner"] > 140.0  # 70% of gross
        assert summary["current_balance"] > 25.0  # Net profit retained
