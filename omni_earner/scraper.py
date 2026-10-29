"""Deterministic Bounty Discovery and GitHub Scraper ($0 LLM cost)."""

import re
from dataclasses import dataclass
from typing import List, Optional
import httpx


@dataclass
class BountyTask:
    """Represents a discovered algorithmic bounty opportunity."""

    task_id: str
    repo: str
    issue_num: int
    title: str
    body: str
    url: str
    bounty_usd: float


# Compiled regular expressions for bounty extraction
BOUNTY_PATTERNS = [
    # Explicit command: /bounty $300 or /bounty 300
    re.compile(
        r"/bounty\s+\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
    # Algora diamond emoji: 💎 $100 or 💎 100
    re.compile(
        r"💎\s*\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
    # Explicit bounty prefix: bounty: $250 or bounty 250
    re.compile(
        r"\bbounty:?\s*\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
    # Currency denomination suffix: 250 USD or 500 USDC
    re.compile(
        r"\b([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(?:USD|USDC)\b",
        re.IGNORECASE,
    ),
    # Standard dollar notation: $150 or $1,200 or $100.00
    re.compile(
        r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
    ),
]


def extract_bounty_usd(
    text: str, labels: Optional[List[str]] = None
) -> float:
    """Extract the highest valid bounty USD amount from text and labels."""
    candidates: List[float] = []

    # Combine text and labels into candidate inspection strings
    haystack = [text]
    if labels:
        haystack.extend(labels)

    for item in haystack:
        if not item:
            continue
        for pattern in BOUNTY_PATTERNS:
            for match in pattern.finditer(item):
                val_str = match.group(1).replace(",", "")
                try:
                    val = float(val_str)
                    if 0 < val <= 1_000_000:  # Sanity range
                        candidates.append(val)
                except ValueError:
                    continue

    if not candidates:
        return 0.0

    return round(max(candidates), 2)


class GitHubBountyScraper:
    """Discovers Algora and Opire bounties from GitHub issues or synthetic seeds."""

    GITHUB_SEARCH_URL = "https://api.github.com/search/issues"

    def fetch_live_bounties(self, limit: int = 5) -> List[BountyTask]:
        """Query GitHub API for open bounties, with graceful fallback to synthetic bounties."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "omni-earner-agent/1.0",
        }
        params = {
            "q": 'label:"💎 Bounty" state:open is:issue no:assignee',
            "sort": "created",
            "order": "desc",
            "per_page": min(limit, 10),
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    self.GITHUB_SEARCH_URL, headers=headers, params=params
                )
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("items", [])
                    tasks: List[BountyTask] = []
                    for item in items:
                        title = item.get("title", "")
                        body = item.get("body", "") or ""
                        labels = [
                            lbl.get("name", "")
                            for lbl in item.get("labels", [])
                        ]
                        bounty = extract_bounty_usd(f"{title}\n{body}", labels)
                        if bounty <= 0:
                            continue

                        repo_url = item.get("repository_url", "")
                        repo_name = (
                            "/".join(repo_url.rstrip("/").split("/")[-2:])
                            if repo_url
                            else "unknown/repo"
                        )
                        issue_num = item.get("number", 0)
                        task_id = f"task-{repo_name.replace('/', '-')}-{issue_num}"

                        tasks.append(
                            BountyTask(
                                task_id=task_id,
                                repo=repo_name,
                                issue_num=issue_num,
                                title=title,
                                body=body,
                                url=item.get("html_url", ""),
                                bounty_usd=bounty,
                            )
                        )
                        if len(tasks) >= limit:
                            break

                    if tasks:
                        return tasks
        except Exception:
            # Fall back to deterministic synthetic bounties on network error or rate limit
            pass

        return self.generate_synthetic_bounties()

    def generate_synthetic_bounties(self) -> List[BountyTask]:
        """Generate 3 realistic test bounties representing diverse triage categories:

        1. High-EV solvable bug ($200 bounty, clear reproduction in calc.py).
        2. Low-EV noise task ($15 bounty, vague description) -> rejected by MAIC.
        3. Trap task ($500 bounty, requires architecture rewrite) -> rejected by triage.
        """
        return [
            # 1. High-EV solvable bug ($200, clear reproduction in calc.py)
            BountyTask(
                task_id="bounty-task-101",
                repo="octo-org/calc-core",
                issue_num=101,
                title="Fix ZeroDivisionError in calculate_average() in calc.py",
                body=(
                    "When an empty list of numbers is provided to calculate_average(), "
                    "the function raises ZeroDivisionError instead of safely returning 0.0. "
                    "File: calc.py. All tests must pass with pytest. /bounty $200"
                ),
                url="https://github.com/octo-org/calc-core/issues/101",
                bounty_usd=200.0,
            ),
            # 2. Low-EV noise task ($15 bounty, vague description)
            BountyTask(
                task_id="bounty-task-102",
                repo="dev-hub/style-assets",
                issue_num=102,
                title="Update README icons and add dark mode screenshots",
                body=(
                    "Can someone update our badges and add dark mode screenshots to the README? "
                    "Need aesthetic adjustments. Bounty $15 USD"
                ),
                url="https://github.com/dev-hub/style-assets/issues/102",
                bounty_usd=15.0,
            ),
            # 3. Trap task ($500 bounty, architectural rewrite, 0.01 win prob)
            BountyTask(
                task_id="bounty-task-103",
                repo="legacy-sys/monolith-backend",
                issue_num=103,
                title="Complete architectural rewrite of Flask backend to Rust",
                body=(
                    "Need complete rewrite of our Python/Flask monolith backend into Rust. "
                    "Must redesign distributed database schema and re-implement all microservices from scratch. "
                    "/bounty $500"
                ),
                url="https://github.com/legacy-sys/monolith-backend/issues/103",
                bounty_usd=500.0,
            ),
        ]
