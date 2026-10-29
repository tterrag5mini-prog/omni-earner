"""Isolated Git + Pytest execution sandbox using temporary environments."""

import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Tuple


class IsolatedSandbox:
    """Manages ephemeral git repositories and subprocess test execution."""

    def __init__(self) -> None:
        self._temp_dirs: List[tempfile.TemporaryDirectory] = []

    def create_mock_repo(
        self,
        buggy_code: str,
        test_code: str,
        filename: str = "calc.py",
        test_filename: str = "test_calc.py",
    ) -> str:
        """Create a standalone git repository with buggy code and test reproduction."""
        temp_dir = tempfile.TemporaryDirectory()
        self._temp_dirs.append(temp_dir)
        workspace_dir = temp_dir.name

        # Initialize git repository with local config
        subprocess.run(
            ["git", "init"],
            cwd=workspace_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "OmniEarner"],
            cwd=workspace_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "bot@omniearner.local"],
            cwd=workspace_dir,
            check=True,
            capture_output=True,
            text=True,
        )

        # Write target code file and pytest test file
        target_path = os.path.join(workspace_dir, filename)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(buggy_code)

        test_path = os.path.join(workspace_dir, test_filename)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(test_code)

        # Stage and commit baseline state
        subprocess.run(
            ["git", "add", "."],
            cwd=workspace_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Baseline repository state with reproduced issue"],
            cwd=workspace_dir,
            check=True,
            capture_output=True,
            text=True,
        )

        return workspace_dir

    def run_tests(self, workspace_dir: str) -> Tuple[bool, str]:
        """Execute pytest in the isolated sandbox environment."""
        env = os.environ.copy()
        env["PYTHONPATH"] = workspace_dir

        try:
            res = subprocess.run(
                [sys.executable, "-m", "pytest", "-v"],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            passed = res.returncode == 0
            output = (res.stdout + "\n" + res.stderr).strip()
            return passed, output
        except subprocess.TimeoutExpired:
            return False, "Execution timed out after 15 seconds"
        except Exception as e:
            return False, f"Subprocess execution error: {e}"

    def apply_fix_and_verify(
        self, workspace_dir: str, target_file: str, fixed_code: str
    ) -> Tuple[bool, str, str]:
        """Apply patch to target_file, capture unified diff, and verify with pytest.

        If tests fail, automatically rolls back via `git checkout -- .`.
        Returns (passed, unified_diff, test_output).
        """
        target_path = os.path.join(workspace_dir, target_file)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)

        # Capture unified diff
        diff_res = subprocess.run(
            ["git", "diff", target_file],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
        )
        unified_diff = diff_res.stdout

        # Verify tests
        passed, test_output = self.run_tests(workspace_dir)

        if not passed:
            # Clean rollback on failure
            subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
            )

        return passed, unified_diff, test_output

    def cleanup(self, workspace_dir: Optional[str] = None) -> None:
        """Clean up temporary sandbox directories."""
        if workspace_dir:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        else:
            for td in self._temp_dirs:
                try:
                    td.cleanup()
                except Exception:
                    pass
            self._temp_dirs.clear()
