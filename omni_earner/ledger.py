"""Survival Constraint and Treasury Circuit Breaker backed by SQLite."""

import sqlite3
import time
from typing import Any, Dict, List, Optional


class CircuitBreakerError(Exception):
    """Raised when an expenditure violates treasury limits or survival constraints."""


class TreasuryLedger:
    """Manages the agent survival budget, revenue allocation, and circuit breakers."""

    def __init__(
        self,
        db_path: str = "treasury.db",
        starting_balance: float = 25.0,
        max_cost_per_task: float = 2.0,
        min_ev_multiplier: float = 3.0,
        target_margin: float = 0.5,
        owner_sweep_ratio: float = 0.70,
    ) -> None:
        self.db_path = db_path
        self.starting_balance = float(starting_balance)
        self.max_cost_per_task = float(max_cost_per_task)
        self.min_ev_multiplier = float(min_ev_multiplier)
        self.target_margin = float(target_margin)
        self.owner_sweep_ratio = float(owner_sweep_ratio)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database tables and seed GENESIS entry if empty."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    balance_after REAL NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    source_url TEXT,
                    bounty_usd REAL DEFAULT 0.0,
                    win_prob REAL DEFAULT 0.0,
                    spent_usd REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'DISCOVERED'
                )
                """
            )

            # Check if ledger is empty
            cursor.execute("SELECT COUNT(*) FROM ledger")
            count = cursor.fetchone()[0]
            if count == 0:
                now = time.time()
                cursor.execute(
                    """
                    INSERT INTO ledger (ts, task_id, kind, amount_usd, balance_after)
                    VALUES (?, 'GENESIS', 'GENESIS', ?, ?)
                    """,
                    (now, self.starting_balance, self.starting_balance),
                )
            conn.commit()

    def get_balance(self) -> float:
        """Return the latest operational treasury balance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT balance_after FROM ledger ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row is not None:
                return round(float(row[0]), 4)
            return round(self.starting_balance, 4)

    def get_task_spend(self, task_id: str) -> float:
        """Return the cumulative compute spend for a given task_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT SUM(ABS(amount_usd)) FROM ledger
                WHERE task_id = ? AND kind LIKE 'DEBIT_%'
                """,
                (task_id,),
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                return round(float(row[0]), 4)
            return 0.0

    def calculate_maic(
        self,
        bounty_usd: float,
        win_prob: float,
        target_margin: Optional[float] = None,
    ) -> float:
        """Calculate Maximum Allowable Inference Cost (MAIC).

        MAIC = Bounty * Win_Probability * (1 - Target_Margin)
        """
        margin = self.target_margin if target_margin is None else target_margin
        return round(float(bounty_usd) * float(win_prob) * (1.0 - float(margin)), 4)

    def can_execute(
        self, estimated_cost: float, bounty_usd: float, win_prob: float
    ) -> bool:
        """Evaluate deterministic Survival Constraint & Expected Value gate.

        Returns True ONLY if:
        1. Treasury operational balance >= estimated_cost
        2. estimated_cost <= MAX_COST_PER_TASK_USD
        3. Expected Value (bounty * win_prob) >= estimated_cost * MIN_EV_MULTIPLIER
        4. estimated_cost <= MAIC
        """
        est_cost = float(estimated_cost)
        bounty = float(bounty_usd)
        prob = float(win_prob)

        # Survival check 1: Solvency
        if self.get_balance() < est_cost:
            return False

        # Survival check 2: Hard Task Budget
        if est_cost > self.max_cost_per_task:
            return False

        # Survival check 3: Expected Value Multiplier Gate
        expected_value = bounty * prob
        required_ev = est_cost * self.min_ev_multiplier
        if expected_value < required_ev:
            return False

        # Survival check 4: MAIC Gate
        maic = self.calculate_maic(bounty, prob, self.target_margin)
        if est_cost > maic:
            return False

        return True

    def register_task(
        self, task_id: str, source_url: str, bounty_usd: float, win_prob: float
    ) -> None:
        """Upsert a discovered task into the tasks table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tasks (task_id, source_url, bounty_usd, win_prob, spent_usd, status)
                VALUES (?, ?, ?, ?, 0.0, 'DISCOVERED')
                ON CONFLICT(task_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    bounty_usd = excluded.bounty_usd,
                    win_prob = excluded.win_prob
                """,
                (task_id, source_url, float(bounty_usd), float(win_prob)),
            )
            conn.commit()

    def record_debit(
        self, task_id: str, amount_usd: float, kind: str = "DEBIT_COMPUTE"
    ) -> float:
        """Record an inference or compute expenditure.

        Raises CircuitBreakerError if task spend cap or balance is violated.
        Returns the new operational balance.
        """
        amount = round(float(amount_usd), 4)
        if amount <= 0:
            return self.get_balance()

        current_spend = self.get_task_spend(task_id)
        if current_spend + amount > self.max_cost_per_task:
            raise CircuitBreakerError(
                f"Circuit breaker tripped: Task '{task_id}' spend would reach "
                f"${current_spend + amount:.4f}, exceeding max limit "
                f"${self.max_cost_per_task:.2f}"
            )

        current_balance = self.get_balance()
        if current_balance - amount < 0:
            raise CircuitBreakerError(
                f"Circuit breaker tripped: Insufficient treasury balance "
                f"(${current_balance:.4f}) to debit ${amount:.4f}"
            )

        new_balance = round(current_balance - amount, 4)
        now = time.time()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ledger (ts, task_id, kind, amount_usd, balance_after)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, task_id, kind, -amount, new_balance),
            )
            cursor.execute(
                """
                INSERT INTO tasks (task_id, source_url, bounty_usd, win_prob, spent_usd, status)
                VALUES (?, '', 0.0, 0.0, ?, 'IN_PROGRESS')
                ON CONFLICT(task_id) DO UPDATE SET
                    spent_usd = round(spent_usd + excluded.spent_usd, 4),
                    status = 'IN_PROGRESS'
                """,
                (task_id, amount),
            )
            conn.commit()

        return new_balance

    def record_revenue(
        self, task_id: str, gross_usd: float, kind: str = "CREDIT_REVENUE"
    ) -> Dict[str, Any]:
        """Record revenue and execute the 70/30 owner cold-wallet sweep.

        - 70% is swept to the owner cold wallet.
        - 30% is retained in the operational treasury.
        Returns a breakdown dict.
        """
        gross = round(float(gross_usd), 4)
        if gross <= 0:
            return {
                "gross": 0.0,
                "swept": 0.0,
                "retained": 0.0,
                "new_balance": self.get_balance(),
            }

        owner_sweep = round(gross * self.owner_sweep_ratio, 4)
        agent_retained = round(gross - owner_sweep, 4)

        current_balance = self.get_balance()
        balance_after_credit = round(current_balance + gross, 4)
        balance_after_sweep = round(balance_after_credit - owner_sweep, 4)

        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Step 1: Log gross revenue
            cursor.execute(
                """
                INSERT INTO ledger (ts, task_id, kind, amount_usd, balance_after)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, task_id, kind, gross, balance_after_credit),
            )
            # Step 2: Log owner sweep to cold wallet
            cursor.execute(
                """
                INSERT INTO ledger (ts, task_id, kind, amount_usd, balance_after)
                VALUES (?, ?, 'OWNER_SWEEP', ?, ?)
                """,
                (now + 0.001, task_id, -owner_sweep, balance_after_sweep),
            )
            cursor.execute(
                """
                INSERT INTO tasks (task_id, source_url, bounty_usd, win_prob, spent_usd, status)
                VALUES (?, '', ?, 1.0, 0.0, 'SETTLED')
                ON CONFLICT(task_id) DO UPDATE SET
                    bounty_usd = excluded.bounty_usd,
                    status = 'SETTLED'
                """,
                (task_id, gross),
            )
            conn.commit()

        return {
            "gross": gross,
            "swept": owner_sweep,
            "retained": agent_retained,
            "new_balance": balance_after_sweep,
        }

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Return all ledger transactions in chronological order."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ledger ORDER BY id ASC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def summary_report(self) -> Dict[str, Any]:
        """Generate a complete financial and operational telemetry report."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Tasks count
            cursor.execute("SELECT COUNT(*) FROM tasks")
            total_tasks = cursor.fetchone()[0]

            # Compute spent
            cursor.execute(
                """
                SELECT SUM(ABS(amount_usd)) FROM ledger
                WHERE kind LIKE 'DEBIT_%'
                """
            )
            row_compute = cursor.fetchone()
            total_compute_spent = (
                round(float(row_compute[0]), 4)
                if row_compute and row_compute[0]
                else 0.0
            )

            # Gross revenue
            cursor.execute(
                """
                SELECT SUM(amount_usd) FROM ledger
                WHERE kind LIKE 'CREDIT_%'
                """
            )
            row_rev = cursor.fetchone()
            total_gross_revenue = (
                round(float(row_rev[0]), 4) if row_rev and row_rev[0] else 0.0
            )

            # Owner swept
            cursor.execute(
                """
                SELECT SUM(ABS(amount_usd)) FROM ledger
                WHERE kind = 'OWNER_SWEEP'
                """
            )
            row_sweep = cursor.fetchone()
            total_swept_owner = (
                round(float(row_sweep[0]), 4)
                if row_sweep and row_sweep[0]
                else 0.0
            )

        current_bal = self.get_balance()
        net_retained = round(total_gross_revenue - total_swept_owner, 4)
        net_profit = round(current_bal - self.starting_balance, 4)
        roi_pct = (
            round((net_profit / self.starting_balance) * 100, 2)
            if self.starting_balance > 0
            else 0.0
        )

        return {
            "total_tasks": total_tasks,
            "total_compute_spent": total_compute_spent,
            "total_gross_revenue": total_gross_revenue,
            "total_swept_to_owner": total_swept_owner,
            "total_swept_owner": total_swept_owner,
            "agent_retained_revenue": net_retained,
            "current_balance": current_bal,
            "current_operational_balance": current_bal,
            "genesis_balance": self.starting_balance,
            "net_agent_profit": net_profit,
            "roi_percent": roi_pct,
        }
