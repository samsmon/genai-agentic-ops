"""Workspace quarantine and automatic rollback for out-of-scope worker modifications.

Implements Phase 2 Defense-in-Depth Quarantine:
- Captures pre-execution byte snapshots of workspace files
- Detects out-of-scope or protected-path modifications post-execution
- Archives unauthorized changes into .agentic/runs/<run_id>/quarantine/ for forensic audit
- Automatically restores the working tree to its clean pre-run baseline state
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
from pathlib import Path
from typing import Any

from orchestrator.governance.protected_paths import (
    canonicalize_path,
    is_path_matching,
    is_protected_path,
)
from orchestrator.governance.scope_check import IGNORED_DIRECTORIES

MAX_BACKUP_FILE_BYTES = 5 * 1024 * 1024  # 5 MB per file cap for in-memory backup


class WorkspaceQuarantine:
    """Manages pre-run file backups, forensic quarantine, and automatic out-of-scope rollback."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.runs_dir = self.root_dir / ".agentic" / "runs"

    def _should_ignore(self, rel_path: str) -> bool:
        parts = rel_path.split("/")
        if any(ignored in parts for ignored in IGNORED_DIRECTORIES):
            return True
        if ".tmp." in rel_path or rel_path.endswith(".pyc"):
            return True
        if rel_path in ("docs/CURRENT_OPS.md", "docs/CURRENT_OPS-archive.md"):
            return True
        return False

    def capture_backup(self) -> dict[str, bytes]:
        """Capture in-memory byte contents of workspace files prior to worker execution."""
        backups: dict[str, bytes] = {}
        for dirpath, dirnames, filenames in os.walk(self.root_dir):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in IGNORED_DIRECTORIES
                and d != "node_modules"
                and not d.startswith(".tmp.")
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
                    if stat.st_size <= MAX_BACKUP_FILE_BYTES:
                        backups[rel_path] = full_path.read_bytes()
                except OSError:
                    continue
        return backups

    def quarantine_and_rollback(
        self,
        run_id: str,
        diff: dict[str, list[str]],
        allowed_paths: list[str],
        protected_paths: list[str] | None,
        backup: dict[str, bytes],
    ) -> list[str]:
        """Quarantine unauthorized modifications and restore the workspace baseline.

        Returns list of relative file paths that were quarantined and rolled back.
        """
        norm_allowed = [p.replace("\\", "/").strip("./") for p in allowed_paths]
        all_modified = diff.get("all_modified", [])
        added_set = set(diff.get("added_files", []))
        quarantined: list[str] = []

        quarantine_dir = self.runs_dir / run_id / "quarantine"
        files_dir = quarantine_dir / "files"

        for mod_path in all_modified:
            is_prot, _ = is_protected_path(mod_path, protected_paths)
            matched = any(is_path_matching(mod_path, ap) for ap in norm_allowed)
            if not is_prot and matched:
                continue

            full_target = self.root_dir / mod_path
            quarantined.append(mod_path)

            # 1. Save offending file content to quarantine forensics directory if it exists
            if full_target.is_file():
                try:
                    q_dest = files_dir / mod_path
                    q_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(full_target, q_dest)
                except OSError:
                    pass

            # 2. Restore original content or remove unauthorized added file
            if mod_path in added_set and mod_path not in backup:
                try:
                    full_target.unlink(missing_ok=True)
                    # Clean up empty parent directories created by rogue worker
                    parent = full_target.parent
                    while parent != self.root_dir and parent.is_dir():
                        if not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                        else:
                            break
                except OSError:
                    pass
            elif mod_path in backup:
                try:
                    full_target.parent.mkdir(parents=True, exist_ok=True)
                    full_target.write_bytes(backup[mod_path])
                except OSError:
                    pass

        if quarantined:
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "schema_version": "1.0",
                "run_id": run_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "quarantined_files": sorted(quarantined),
            }
            manifest_file = quarantine_dir / "manifest.json"
            manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return sorted(quarantined)
