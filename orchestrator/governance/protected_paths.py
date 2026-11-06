"""Built-in non-overridable protected paths and path canonicalization.

Implements Threat Model Section 2.2 and 2.5:
- Unalterable list of built-in protected paths
- Windows path canonicalization and case-insensitivity
- Directory traversal rejection
- Overlap detection between allowed_paths and protected_paths
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

# Built-in non-overridable protected paths from Threat Model 2.2
BUILTIN_PROTECTED_PATHS: tuple[str, ...] = (
    ".git",
    ".agentic/config",
    ".claude",
    ".githooks",
    "RULES.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "kit",
)


def canonicalize_path(path: str | Path, root_dir: str | Path) -> str:
    """Canonicalize a path relative to root_dir.

    Uses forward slashes, strips redundant separators, rejects traversal outside root,
    and normalizes case on Windows.
    """
    root = Path(root_dir).resolve()
    target = Path(path)

    if target.is_absolute():
        resolved = target.resolve()
    else:
        resolved = (root / target).resolve()

    # Verify no traversal outside root_dir
    try:
        rel = resolved.relative_to(root)
    except ValueError as e:
        raise ValueError(
            f"Path traversal detected: '{path}' resolves outside root '{root_dir}'"
        ) from e

    rel_str = rel.as_posix()
    if rel_str == ".":
        rel_str = ""

    return rel_str


def is_path_matching(path_rel: str, pattern: str) -> bool:
    """Check if normalized relative path matches a pattern or directory prefix."""
    p = path_rel.rstrip("/")
    pat = pattern.rstrip("/")

    if IS_WINDOWS:
        p = p.lower()
        pat = pat.lower()

    if p == pat:
        return True
    if p.startswith(pat + "/"):
        return True
    # If pattern is a prefix with wildcard or prefix match
    if pat.endswith("*"):
        prefix = pat[:-1]
        if p.startswith(prefix):
            return True
    return False


def is_protected_path(
    path_rel: str,
    extra_protected: list[str] | None = None,
) -> tuple[bool, str]:
    """Check if a relative path matches any built-in or custom protected path.

    Returns (is_protected, matched_protected_path).
    """
    all_protected = list(BUILTIN_PROTECTED_PATHS)
    if extra_protected:
        all_protected.extend(extra_protected)

    for protected in all_protected:
        if is_path_matching(path_rel, protected):
            return True, protected
    return False, ""


def check_path_overlap_with_protected(
    allowed_paths: list[str],
    extra_protected: list[str] | None = None,
) -> list[str]:
    """Return any allowed_path that conflicts with or covers a protected path."""
    conflicts: list[str] = []
    all_protected = list(BUILTIN_PROTECTED_PATHS)
    if extra_protected:
        all_protected.extend(extra_protected)

    for allowed in allowed_paths:
        norm_allowed = allowed.replace("\\", "/").strip("./")
        if not norm_allowed or norm_allowed == "/":
            conflicts.append(f"Root path '/' is forbidden in allowed_paths")
            continue

        for protected in all_protected:
            # Overlap in either direction: allowed is within protected, or allowed encloses protected
            if is_path_matching(norm_allowed, protected) or is_path_matching(
                protected, norm_allowed
            ):
                conflicts.append(
                    f"allowed_path '{allowed}' overlaps protected path '{protected}'"
                )
    return conflicts
