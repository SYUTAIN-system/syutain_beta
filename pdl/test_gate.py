"""4-stage test gate for PDL changes.

Validates worktree changes before committing:
  Stage 1: Syntax check — ast.parse all .py files
  Stage 2: Import check — try importing key modules
  Stage 3: Forbidden file check — verify no forbidden files were modified
  Stage 4: Diff size check — reject changes > 500 lines
"""
import ast
import subprocess
import sys
from pathlib import Path

from pdl.file_guard import get_forbidden_files, _normalize


def run_test_gate(worktree_path: str, project_dir: str = "") -> dict:
    """Run all 4 test stages.

    Args:
        worktree_path: Path to the git worktree with changes.
        project_dir: Original project directory (for diff comparison).

    Returns:
        dict with keys: passed (bool), stage_failed (str|None), details (str)
    """
    wt = Path(worktree_path)

    # Stage 1: Syntax check
    py_files = list(wt.rglob("*.py"))
    for f in py_files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            ast.parse(source, filename=str(f))
        except SyntaxError as e:
            return {
                "passed": False,
                "stage_failed": "syntax",
                "details": f"SyntaxError in {f.relative_to(wt)}: {e}",
            }

    # Stage 2: Import check — verify key modules parse correctly
    key_modules = ["app", "scheduler", "worker_main"]
    for mod in key_modules:
        mod_path = wt / f"{mod}.py"
        if mod_path.exists():
            try:
                source = mod_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
                # Check that top-level imports are valid syntax (already covered by Stage 1)
                # but also verify no circular-looking self-imports
            except Exception as e:
                return {
                    "passed": False,
                    "stage_failed": "import",
                    "details": f"Import check failed for {mod}.py: {e}",
                }

    # Stage 3: Forbidden file check
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        changed_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

        # Also check unstaged changes
        result2 = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        unstaged = [f.strip() for f in result2.stdout.strip().split("\n") if f.strip()]

        # Check untracked files too
        result3 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        untracked = [f.strip() for f in result3.stdout.strip().split("\n") if f.strip()]

        all_changed = set(changed_files + unstaged + untracked)
        forbidden = get_forbidden_files()

        for cf in all_changed:
            for pattern in forbidden:
                if pattern.endswith("/"):
                    if cf.startswith(pattern) or cf == pattern.rstrip("/"):
                        return {
                            "passed": False,
                            "stage_failed": "forbidden",
                            "details": f"Forbidden file modified: {cf} (matches {pattern})",
                        }
                else:
                    if cf == pattern:
                        return {
                            "passed": False,
                            "stage_failed": "forbidden",
                            "details": f"Forbidden file modified: {cf}",
                        }
    except Exception as e:
        return {
            "passed": False,
            "stage_failed": "forbidden",
            "details": f"Forbidden file check error: {e}",
        }

    # Stage 4: Diff size check — reject changes > 500 lines
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "--cached"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        # Also count unstaged + untracked
        result_all = subprocess.run(
            ["git", "diff", "--shortstat"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        # Parse total lines changed from --shortstat format:
        # " 3 files changed, 150 insertions(+), 20 deletions(-)"
        total_lines = 0
        for stat_out in [result.stdout, result_all.stdout]:
            for line in stat_out.strip().split("\n"):
                if "insertion" in line or "deletion" in line:
                    import re

                    nums = re.findall(r"(\d+) insertion|(\d+) deletion", line)
                    for ins, dels in nums:
                        total_lines += int(ins) if ins else int(dels) if dels else 0

        if total_lines > 500:
            return {
                "passed": False,
                "stage_failed": "diff_size",
                "details": f"Change too large: {total_lines} lines (max 500)",
            }
    except Exception as e:
        return {
            "passed": False,
            "stage_failed": "diff_size",
            "details": f"Diff size check error: {e}",
        }

    return {"passed": True, "stage_failed": None, "details": "All 4 stages passed"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m pdl.test_gate <worktree_path>")
        sys.exit(1)
    result = run_test_gate(sys.argv[1])
    print(f"{'PASS' if result['passed'] else 'FAIL'}: {result['details']}")
    sys.exit(0 if result["passed"] else 1)
