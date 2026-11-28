"""kit/install.py --uninstall: remove only what the receipt proves is still the installer's own.

A copied file goes when its content still matches the receipt. A merged hook file loses only the kit's hook entries.
AGENTS.md loses only the rules block. Ops logs, pointer lines and a hidden-mode overlay are left alone.
"""
import json
import os
import shutil

try:
    from receipt import RECEIPT, load_receipt, untouched
    from sources import BEGIN_RE, END_RE, Fail, dumps, git, parse_manifest, print_plan
except ImportError:
    from kit.receipt import RECEIPT, load_receipt, untouched  # type: ignore[no-redef]
    from kit.sources import BEGIN_RE, END_RE, Fail, dumps, git, parse_manifest, print_plan  # type: ignore[no-redef]

NAMED_HOOK = "agentic-ops-guard"


def _commands(obj):
    """Every hook command string anywhere inside obj."""
    if isinstance(obj, dict):
        own = [v for k, v in obj.items() if k in ("command", "commandWindows") and isinstance(v, str)]
        return own + [c for v in obj.values() for c in _commands(v)]
    if isinstance(obj, list):
        return [c for v in obj for c in _commands(v)]
    return []


def _norm(command):
    return "python " + command[8:] if command.startswith("python3 ") else command


def strip_hooks(obj, ours):
    """obj without the kit's hook entries; containers that become empty because of that are dropped."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == NAMED_HOOK:
                continue
            new = strip_hooks(v, ours)
            if new != v and new in ({}, []):
                continue
            out[k] = new
        return out
    if isinstance(obj, list):
        out = []
        for item in obj:
            cmds = _commands(item)
            if cmds and all(_norm(c) in ours for c in cmds):
                continue
            out.append(strip_hooks(item, ours))
        return out
    return obj


def _safe_path(project, rel):
    root = os.path.realpath(project)
    full = os.path.realpath(os.path.join(root, *rel.split("/")))
    if os.path.isabs(rel) or ".." in rel.split("/") or not os.path.normcase(full).startswith(os.path.normcase(root + os.sep)):
        raise Fail(2, f"the receipt lists a path outside the project, nothing was removed: {rel}")
    return os.path.join(project, *rel.split("/"))


def build_removal(project, src, force):
    receipt = load_receipt(project)
    if receipt is None:
        raise Fail(2, f"no readable install receipt at {RECEIPT}: nothing can be removed safely")
    merged = {e["dst"]: e["src"] for e in parse_manifest(src.kit("MANIFEST").decode("utf-8")) if e["mode"] == "merge-json"}
    pre = set(receipt.get("preexisting", []))
    plan, kept = [], {}

    def item(action, path, detail="", data=None):
        plan.append(dict(action=action, path=path, detail=detail, data=data))

    for rel, recorded in receipt["files"].items():
        full = _safe_path(project, rel)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as f:
            cur = f.read()
        if rel in pre:
            item("keep", rel, "was there before the install")
        elif rel in merged:
            kit = json.loads(src.kit(merged[rel]).decode("utf-8"))
            ours = {_norm(c) for c in _commands(kit)}
            try:
                doc = json.loads(cur.decode("utf-8"))
            except ValueError:
                item("keep", rel, "not valid JSON, remove the kit hooks by hand")
                kept[rel] = recorded
                continue
            left = strip_hooks(doc, ours)
            if left == strip_hooks(kit, ours):
                item("remove", rel)
            elif left == doc:
                item("keep", rel, "no kit hook left in it")
            else:
                item("strip", rel, "kit hooks removed, your other settings kept", data=dumps(left).encode("utf-8"))
        elif force or untouched(cur, recorded):
            item("remove", rel)
        else:
            item("keep", rel, "changed since the install; --force removes it")
            kept[rel] = recorded

    agents = os.path.join(project, "AGENTS.md")
    if os.path.isfile(agents):
        with open(agents, "rb") as f:
            raw = f.read().decode("utf-8")
        text = raw.replace("\r\n", "\n")
        begin, end = BEGIN_RE.search(text), END_RE.search(text)
        if begin and end and begin.start() < end.start():
            parts = [p.strip("\n") for p in (text[:begin.start()], text[end.end():])]
            left = "\n\n".join(p for p in parts if p)
            if not left:
                item("remove", "AGENTS.md", "it held only the rules block")
            else:
                nl = "\r\n" if "\r\n" in raw else "\n"
                item("strip", "AGENTS.md", "rules block removed", data=(left + "\n").replace("\n", nl).encode("utf-8"))
        elif begin or end:
            item("keep", "AGENTS.md", "damaged markers, remove the block by hand")

    if kept:
        item("update", RECEIPT, "lists the files that were kept", data=dumps(dict(receipt, files=kept)).encode("utf-8"))
    else:
        item("remove", RECEIPT, "install receipt")
    return plan


def _prune(project, folder):
    """Delete folder and its parents while they hold nothing but bytecode caches; never the project root."""
    root = os.path.abspath(project)
    folder = os.path.abspath(folder)
    while folder != root and folder.startswith(root + os.sep) and os.path.isdir(folder):
        names = os.listdir(folder)
        if any(n != "__pycache__" for n in names):
            return
        for n in names:
            shutil.rmtree(os.path.join(folder, n))
        os.rmdir(folder)
        folder = os.path.dirname(folder)


def run_uninstall(project, src, apply, force):
    project = os.path.abspath(project)
    plan = build_removal(project, src, force)
    print(f"writgate uninstall ({'APPLY' if apply else 'dry run'}) from {project}")
    print_plan(plan, apply)
    print("  left alone: ops logs, pointer lines (CLAUDE.md, GEMINI.md, .cursorrules), non-hook settings "
          "added to a merged file, and a hidden-mode overlay")
    if not apply:
        print("Dry run: nothing was removed. Re-run with --apply to uninstall.")
        return 0
    folders = set()
    for p in plan:
        full = os.path.join(project, *p["path"].split("/"))
        if p["action"] == "remove":
            os.remove(full)
            folders.add(os.path.dirname(full))
        elif p["action"] in ("strip", "update"):
            with open(full, "wb") as f:
                f.write(p["data"])
    for folder in sorted(folders, key=len, reverse=True):
        _prune(project, folder)
    _, hooks = git(project, "config", "--get", "core.hooksPath")
    if hooks == ".githooks" and not os.path.isdir(os.path.join(project, ".githooks")):
        git(project, "config", "--unset", "core.hooksPath")
        print("  unset core.hooksPath")
    print("Uninstalled. Nothing was committed or pushed.")
    return 0
