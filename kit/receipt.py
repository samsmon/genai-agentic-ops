"""The install receipt (INSTALLED.json): what kit/install.py wrote, used to upgrade and uninstall safely."""
import json
import os

try:
    from sources import sha
except ImportError:
    from kit.sources import sha  # type: ignore[no-redef]

RECEIPT = "scripts/agentic-ops/INSTALLED.json"


def load_receipt(project):
    """The receipt as a dict with a "files" dict, or None when it is missing or unreadable."""
    try:
        with open(os.path.join(project, *RECEIPT.split("/")), "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None


def untouched(cur, recorded):
    """True when the file still has the recorded content; a line-ending conversion does not count as a change."""
    lf = cur.replace(b"\r\n", b"\n")
    return recorded in (sha(cur), sha(lf), sha(lf.replace(b"\n", b"\r\n")))


def next_receipt(project, old, meta, files, found):
    """The receipt to write. `found` lists files that were already there, identical to the kit, in this run.

    Files from an earlier install that this selection leaves out stay listed while they exist, so uninstall sees them.
    A file that was there before the first install is remembered as preexisting and is never removed.
    """
    old_files = (old or {}).get("files", {})
    hashes = {k: sha(v) for k, v in files.items()}
    for k, v in old_files.items():
        if k not in hashes and os.path.isfile(os.path.join(project, *k.split("/"))):
            hashes[k] = v
    pre = set((old or {}).get("preexisting", [])) | {k for k in found if k not in old_files}
    out = dict(meta, files=dict(sorted(hashes.items())))
    if pre:
        out["preexisting"] = sorted(pre)
    return out
