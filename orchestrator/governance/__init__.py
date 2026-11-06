"""Governance and safety layer for orchestrator."""
from orchestrator.governance.approval import ApprovalManager
from orchestrator.governance.audit import AuditLogger
from orchestrator.governance.lock import LockManager
from orchestrator.governance.policy_bridge import PolicyBridge
from orchestrator.governance.projection import CurrentOpsProjector
from orchestrator.governance.protected_paths import (
    canonicalize_path,
    is_path_matching,
    is_protected_path,
)
from orchestrator.governance.scope_check import ScopeChecker

__all__ = [
    "ApprovalManager",
    "AuditLogger",
    "CurrentOpsProjector",
    "LockManager",
    "PolicyBridge",
    "ScopeChecker",
    "canonicalize_path",
    "is_path_matching",
    "is_protected_path",
]
