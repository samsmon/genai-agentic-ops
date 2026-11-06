"""Filesystem baseline snapshotting and post-execution scope verification.

Implements M1 baseline snapshotting and diff verification against allowed_paths
and built-in non-overridable protected paths.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from orchestrator.governance.protected_paths import (
    canonicalize_path,
    is_path_matching,
    is_protected_path,
)

IGNORED_DIRECTORIES: tuple[str, ...] = (
    ".git",
    ".agentic",
    "__pycache__",
    ".pytest_cache",
)

SOURCE_EXTENSIONS: tuple[str, ...] = (
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".py",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".cs",
)

VENDOR_OR_MIN_PATTERNS: tuple[str, ...] = (
    ".min.",
    ".bundle.",
    "vendor/",
    "vendor\\",
    "node_modules/",
    "node_modules\\",
)

MAX_SOURCE_LINES: int = 500


def hash_file(file_path: Path) -> str:
    """Calculate SHA256 hex digest of a file in binary mode."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


class ScopeChecker:
    """Captures baseline snapshots and verifies workspace diffs against policy."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()

    def _should_ignore(self, rel_path: str) -> bool:
        """Check if a path belongs to an internal orchestrator or VCS folder."""
        parts = rel_path.split("/")
        if any(ignored in parts for ignored in IGNORED_DIRECTORIES):
            return True
        if ".tmp." in rel_path or rel_path.endswith(".pyc"):
            return True
        if rel_path in ("docs/CURRENT_OPS.md", "docs/CURRENT_OPS-archive.md"):
            return True
        return False

    def capture_snapshot(self) -> dict[str, Any]:
        """Scan workspace and compute SHA256 hashes for all non-ignored files."""
        files: dict[str, dict[str, Any]] = {}

        for dirpath, dirnames, filenames in os.walk(self.root_dir):
            # Prune ignored directories in-place
            dirnames[:] = [
                d
                for d in dirnames
                if d not in IGNORED_DIRECTORIES and not d.startswith(".tmp.")
            ]

            for fname in filenames:
                full_path = Path(dirpath) / fname
                try:
                    rel_path = canonicalize_path(full_path, self.root_dir)
                except ValueError:
                    continue

                if self._should_ignore(rel_path):
                    continue

                try:
                    stat = full_path.stat()
                    f_hash = hash_file(full_path)
                    files[rel_path] = {
                        "sha256": f_hash,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                except OSError:
                    continue

        # Canonical overall snapshot hash
        sorted_items = sorted(
            f"{path}:{meta['sha256']}" for path, meta in files.items()
        )
        overall_hash = hashlib.sha256(
            "\n".join(sorted_items).encode("utf-8")
        ).hexdigest()

        return {
            "snapshot_hash": overall_hash,
            "file_count": len(files),
            "files": files,
        }

    def compute_diff(
        self,
        baseline_snapshot: dict[str, Any],
        current_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, list[str]]:
        """Compare baseline snapshot with current snapshot, returning diff lists."""
        if current_snapshot is None:
            current_snapshot = self.capture_snapshot()

        base_files = baseline_snapshot.get("files", {})
        curr_files = current_snapshot.get("files", {})

        changed_files: list[str] = []
        added_files: list[str] = []
        deleted_files: list[str] = []

        for path, curr_meta in curr_files.items():
            if path not in base_files:
                added_files.append(path)
            elif curr_meta["sha256"] != base_files[path]["sha256"]:
                changed_files.append(path)

        for path in base_files:
            if path not in curr_files:
                deleted_files.append(path)

        return {
            "changed_files": sorted(changed_files),
            "added_files": sorted(added_files),
            "deleted_files": sorted(deleted_files),
            "all_modified": sorted(changed_files + added_files + deleted_files),
        }

    def verify_scope(
        self,
        diff: dict[str, list[str]],
        allowed_paths: list[str],
        protected_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Verify that all modified files comply with allowed_paths and protected_paths.

        Returns a dictionary conforming to result.schema.json diff object.
        """
        all_modified = diff.get("all_modified", [])
        violations: list[str] = []

        # Normalize allowed paths
        norm_allowed = [p.replace("\\", "/").strip("./") for p in allowed_paths]

        for mod_path in all_modified:
            # 1. Check if modified file is a protected path
            is_prot, prot_name = is_protected_path(mod_path, protected_paths)
            if is_prot:
                violations.append(
                    f"Protected path modified: '{mod_path}' matches protected '{prot_name}'"
                )
                continue

            # 2. Check if modified file matches any allowed_paths
            matched = any(is_path_matching(mod_path, ap) for ap in norm_allowed)
            if not matched:
                violations.append(
                    f"Out-of-scope path modified: '{mod_path}' not in allowed_paths"
                )
                continue

            # 3. Anti-monolith verification: check if source file exceeds line limit
            norm_mod = mod_path.replace("\\", "/").lower()
            if any(norm_mod.endswith(ext) for ext in SOURCE_EXTENSIONS):
                if not any(v in norm_mod for v in VENDOR_OR_MIN_PATTERNS):
                    full_p = self.root_dir / mod_path
                    if full_p.is_file():
                        try:
                            with open(full_p, "r", encoding="utf-8", errors="replace") as f:
                                line_count = sum(1 for _ in f)
                            if line_count > MAX_SOURCE_LINES:
                                violations.append(
                                    f"Anti-monolith violation: source file '{mod_path}' exceeds "
                                    f"{MAX_SOURCE_LINES} lines ({line_count} lines). Modularize into smaller components (<300 lines recommended)."
                                )
                        except OSError:
                            pass

        in_scope = len(violations) == 0

        return {
            "changed_files": diff.get("changed_files", []),
            "staged_files": [],
            "untracked_files": diff.get("added_files", []),
            "in_scope": in_scope,
            "violations": violations,
        }
