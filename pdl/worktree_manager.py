"""Git worktree manager for PDL parallel sessions"""
import os
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger("syutain.pdl.worktree")

WORKTREE_BASE = "/tmp/pdl_worktrees"
MAX_WORKTREES = 5
TTL_HOURS = 24


async def create_worktree(task_id: str) -> str:
    """Create isolated git worktree for a task.

    Returns the path to the created worktree directory.
    Raises RuntimeError if max worktrees exceeded or git command fails.
    """
    base = Path(WORKTREE_BASE)
    base.mkdir(parents=True, exist_ok=True)

    # Check current worktree count
    current = await list_worktrees()
    if len(current) >= MAX_WORKTREES:
        # Try cleaning stale ones first
        await cleanup_stale_worktrees()
        current = await list_worktrees()
        if len(current) >= MAX_WORKTREES:
            raise RuntimeError(
                f"Max worktrees ({MAX_WORKTREES}) reached. "
                "Clean up before creating new ones."
            )

    branch_name = f"pdl/task-{task_id}"
    worktree_path = str(base / f"task-{task_id}")

    try:
        # Create a new branch from current HEAD
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, worktree_path],
            capture_output=True, text=True, check=True,
            cwd=os.environ.get("PROJECT_DIR", os.path.expanduser("~/syutain_beta"))
        )
        logger.info("Created worktree: %s (branch: %s)", worktree_path, branch_name)

        # Write metadata for TTL tracking
        meta_path = Path(worktree_path) / ".pdl_meta"
        meta_path.write_text(
            f"task_id={task_id}\n"
            f"created_at={datetime.utcnow().isoformat()}\n"
            f"branch={branch_name}\n"
        )

        return worktree_path
    except subprocess.CalledProcessError as e:
        logger.error("Failed to create worktree: %s", e.stderr)
        raise RuntimeError(f"git worktree add failed: {e.stderr}") from e


async def cleanup_worktree(worktree_path: str):
    """Remove a worktree after task completion."""
    project_dir = os.environ.get(
        "PROJECT_DIR", os.path.expanduser("~/syutain_beta")
    )
    wt = Path(worktree_path)

    if not wt.exists():
        logger.warning("Worktree path does not exist: %s", worktree_path)
        return

    # Read branch name from metadata if available
    branch_name = None
    meta_path = wt / ".pdl_meta"
    if meta_path.exists():
        for line in meta_path.read_text().splitlines():
            if line.startswith("branch="):
                branch_name = line.split("=", 1)[1]

    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_path],
            capture_output=True, text=True, check=True,
            cwd=project_dir
        )
        logger.info("Removed worktree: %s", worktree_path)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to remove worktree: %s", e.stderr)

    # Delete the branch if we know it
    if branch_name:
        try:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                capture_output=True, text=True, check=True,
                cwd=project_dir
            )
            logger.info("Deleted branch: %s", branch_name)
        except subprocess.CalledProcessError:
            pass  # Branch may already be gone


async def cleanup_stale_worktrees():
    """Remove worktrees older than TTL."""
    base = Path(WORKTREE_BASE)
    if not base.exists():
        return

    cutoff = datetime.utcnow() - timedelta(hours=TTL_HOURS)

    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / ".pdl_meta"
        if not meta_path.exists():
            # No metadata — check directory mtime as fallback
            mtime = datetime.utcfromtimestamp(entry.stat().st_mtime)
            if mtime < cutoff:
                logger.info("Cleaning stale worktree (no meta, mtime): %s", entry)
                await cleanup_worktree(str(entry))
            continue

        # Parse created_at from metadata
        created_at = None
        for line in meta_path.read_text().splitlines():
            if line.startswith("created_at="):
                try:
                    created_at = datetime.fromisoformat(line.split("=", 1)[1])
                except ValueError:
                    pass

        if created_at and created_at < cutoff:
            logger.info("Cleaning stale worktree (TTL expired): %s", entry)
            await cleanup_worktree(str(entry))


async def list_worktrees() -> list:
    """List all active PDL worktrees.

    Returns a list of dicts with keys: path, task_id, created_at, branch.
    """
    base = Path(WORKTREE_BASE)
    if not base.exists():
        return []

    worktrees = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue

        info = {"path": str(entry), "task_id": None, "created_at": None, "branch": None}

        meta_path = entry / ".pdl_meta"
        if meta_path.exists():
            for line in meta_path.read_text().splitlines():
                if "=" in line:
                    key, val = line.split("=", 1)
                    if key in ("task_id", "created_at", "branch"):
                        info[key] = val

        worktrees.append(info)

    return worktrees
