"""File protection for PDL — prevents Session B from modifying critical files."""
import os
from pathlib import Path
from functools import lru_cache

import yaml


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


@lru_cache(maxsize=1)
def load_protection_config() -> dict:
    """Load file protection rules from pdl/config.yaml.

    Returns dict with 'forbidden' and 'review_required' lists.
    """
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    return config.get("file_protection", {"forbidden": [], "review_required": []})


def _normalize(filepath: str) -> str:
    """Normalize filepath to project-relative form."""
    project_root = os.path.expanduser("~/syutain_beta")
    abspath = os.path.abspath(filepath)
    if abspath.startswith(project_root):
        return os.path.relpath(abspath, project_root)
    return filepath


def check_file_permission(filepath: str) -> str:
    """Check if a file can be modified by Session B.

    Args:
        filepath: Absolute or project-relative path.

    Returns:
        'allowed' — Session B can freely modify.
        'review_required' — Session B can modify but needs human review before merge.
        'forbidden' — Session B must never modify.
    """
    config = load_protection_config()
    rel = _normalize(filepath)

    # Check forbidden list — also matches prefix for directory rules (e.g. "pdl/")
    for pattern in config.get("forbidden", []):
        if pattern.endswith("/"):
            if rel.startswith(pattern) or rel == pattern.rstrip("/"):
                return "forbidden"
        else:
            if rel == pattern:
                return "forbidden"

    # Check review_required list
    for pattern in config.get("review_required", []):
        if rel == pattern:
            return "review_required"

    return "allowed"


def get_forbidden_files() -> list:
    """Get list of files/patterns Session B must never modify.

    Returns a flat list of relative paths/patterns suitable for
    passing to Claude as a space-separated string via CLI args.
    """
    config = load_protection_config()
    return list(config.get("forbidden", []))


def get_forbidden_files_str() -> str:
    """Get forbidden files as a single space-separated string for CLI use."""
    return " ".join(get_forbidden_files())


def validate_changeset(filepaths: list[str]) -> dict:
    """Validate a set of files against protection rules.

    Args:
        filepaths: List of file paths to check.

    Returns:
        Dict with keys 'allowed', 'review_required', 'forbidden',
        each containing a list of file paths.
    """
    result = {"allowed": [], "review_required": [], "forbidden": []}
    for fp in filepaths:
        permission = check_file_permission(fp)
        result[permission].append(fp)
    return result
