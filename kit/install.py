#!/usr/bin/env python3
"""genai-agentic-ops installer: the mechanical part of Part A, done the same way every time.

It copies only the kit files you select (kit/MANIFEST is the one list), merges the Part B rules block into AGENTS.md
between its markers, adds pointer lines, creates the ops log from the Part C templates, writes an install receipt,
and in hidden mode runs `agentic-sync init`. It never commits and never pushes. The default is a dry run: it prints
the plan and writes nothing until you add --apply.

  python install.py --tools antigravity,claude --modules guard,githooks,scripts --shell ps \\
                    --visibility hidden --policy agent-commits --project <dir> [--apply]

Kit source: --kit-dir <checkout>/kit (default: the folder of this file) or --pin <commit-sha> (downloads from
https://raw.githubusercontent.com/samsmon/genai-agentic-ops/<sha>/..., base overridable with AGENTIC_OPS_RAW_BASE).

Exit codes: 0 ok (also for a dry run) | 2 usage or not a git work tree | 3 hidden mode but agentic files are already
tracked in the project history (nothing is written) | 4 a decision is needed: existing files differ (use --force) or
the AGENTS.md markers are damaged (nothing is written) | 5 hidden-mode sync stopped (its own code is printed) |
6 kit source unreachable.
"""
import argparse
import json
import os
import sys

try:
    from sources import (
        Fail,
        LocalSource,
        RemoteSource,
        apply_plan,
        compose_block,
        dumps,
        git,
        merge_block,
        merge_json,
        parse_manifest,
        print_plan,
        read_text,
        rules_parts,
        run_sync,
        select,
        sha,
        short_diff,
    )
except ImportError:
    from kit.sources import (  # type: ignore[no-redef]
        Fail,
        LocalSource,
        RemoteSource,
        apply_plan,
        compose_block,
        dumps,
        git,
        merge_block,
        merge_json,
        parse_manifest,
        print_plan,
        read_text,
        rules_parts,
        run_sync,
        select,
        sha,
        short_diff,
    )

TOOLS = ("claude", "codex", "cursor", "opencode", "antigravity")
MODULES = ("guard", "githooks", "scripts", "handoff", "tests")
SHELLS = ("ps", "sh")
TRACKED_CHECK = [
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", "docs/CURRENT_OPS.md",
    "docs/CURRENT_OPS-archive.md", "docs/HARNESS_DECLINED.md", ".claude/", ".cursor/",
    ".codex/", ".agents/", ".agent/", ".opencode/", ".githooks/", "scripts/agentic-ops/",
]
POINTER_LINE = "Read AGENTS.md for the project rules."
RECEIPT = "scripts/agentic-ops/INSTALLED.json"


def build_plan(a, src):
    project = os.path.abspath(a.project)
    rc, _ = git(project, "rev-parse", "--is-inside-work-tree")
    if rc != 0:
        raise Fail(2, f"{project} is not inside a git work tree")
    _, top = git(project, "rev-parse", "--show-toplevel")
    project = os.path.normpath(top) if top else project
    hidden = a.visibility == "hidden"
    tools = [t for t in a.tools.split(",") if t]
    modules = [m for m in a.modules.split(",") if m]
    for t in tools:
        if t not in TOOLS:
            raise Fail(2, f"unknown tool {t!r} (choose from {', '.join(TOOLS)})")
    for m in modules:
        if m not in MODULES:
            raise Fail(2, f"unknown module {m!r} (choose from {', '.join(MODULES)})")
    if hidden and "scripts" not in modules:
        raise Fail(2, "hidden mode needs the scripts module (agentic-sync); add it to --modules or use --visibility visible")
    if tools and "guard" not in modules:
        raise Fail(2, "--tools needs the guard module")

    if hidden:
        rc, tracked = git(project, "ls-files", "--", *TRACKED_CHECK)
        if tracked:
            raise Fail(3, "hidden mode: these agentic files are already tracked in the project history, nothing was written:\n  "
                          + tracked.replace("\n", "\n  ")
                          + "\nKeep them visible (--visibility visible) or untrack them yourself knowing the history keeps them; "
                            "the installer never rewrites history.")

    entries = select(parse_manifest(src.kit("MANIFEST").decode("utf-8")), tools, modules, a.shell)
    parts = rules_parts(src.root("RULES.md").decode("utf-8"))
    plan, files = [], {}

    def item(action, path, detail="", data=None, mode=None):
        plan.append(dict(action=action, path=path, detail=detail, data=data, mode=mode))

    for e in entries:
        data = src.kit(e["src"])
        dst = os.path.join(project, *e["dst"].split("/"))
        cur = None
        if os.path.isfile(dst):
            with open(dst, "rb") as f:
                cur = f.read()
        if e["mode"] == "merge-json":
            try:
                merged = merge_json(json.loads(cur.decode("utf-8")) if cur else {}, json.loads(data.decode("utf-8")))
            except ValueError:
                item("conflict", e["dst"], "existing file is not valid JSON, merge it by hand")
                continue
            out = dumps(merged).encode("utf-8") if cur else data
            if cur is not None and json.loads(cur.decode("utf-8")) == merged:
                item("unchanged", e["dst"], "hook entry already present")
            elif cur is None:
                item("create", e["dst"], data=out)
            else:
                item("merge", e["dst"], "hook entry merged into the existing file", data=out)
            files[e["dst"]] = out
            continue
        files[e["dst"]] = data
        if cur is None:
            item("create", e["dst"], data=data, mode=e["mode"])
        elif cur.replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n"):
            item("unchanged", e["dst"])
        else:
            item("conflict", e["dst"], short_diff(cur.decode("utf-8", "replace"), data.decode("utf-8", "replace"), e["dst"]),
                 data=data, mode=e["mode"])

    # AGENTS.md block, pointer lines, ops log
    blk = compose_block(parts, a.policy, hidden, "handoff" in modules)
    cur = read_text(os.path.join(project, "AGENTS.md"))
    act, new, note = merge_block(cur, blk)
    if act == "stop":
        item("stop", "AGENTS.md", note)
    elif act == "unchanged":
        item("unchanged", "AGENTS.md", note)
    else:
        item(act, "AGENTS.md", note, data=new.encode("utf-8"))

    def pointer(name, create_text, only_if_exists, mention):
        p = os.path.join(project, name)
        t = read_text(p)
        if t is None:
            if only_if_exists:
                return
            item("create", name, "pointer file", data=create_text.encode("utf-8"))
        elif mention in t:
            item("unchanged", name, "already points to AGENTS.md")
        else:
            nl = "\r\n" if "\r\n" in t else "\n"
            body = t if t.endswith(("\n", "\r\n")) or not t else t + nl
            item("append", name, "pointer line added", data=(body + create_text.strip() + nl).encode("utf-8"))

    if "claude" in tools:
        pointer("CLAUDE.md", "@AGENTS.md\n", False, "@AGENTS.md")
    pointer("GEMINI.md", POINTER_LINE + "\n", True, "AGENTS.md")
    pointer(".cursorrules", POINTER_LINE + "\n", True, "AGENTS.md")

    ops = os.path.join(project, "docs", "CURRENT_OPS.md")
    elsewhere = [n for n in ("CURRENT_OPS.md", "current_ops.md") if os.path.isfile(os.path.join(project, n))] + \
                [n for n in ("docs/current_ops.md",) if os.path.isfile(os.path.join(project, *n.split("/")))]
    if os.path.isfile(ops):
        item("unchanged", "docs/CURRENT_OPS.md", "ops log kept as it is")
    elif elsewhere:
        item("skip", "docs/CURRENT_OPS.md", f"an ops log already exists at {elsewhere[0]}: keep, move or merge it by hand (Part A)")
    else:
        item("create", "docs/CURRENT_OPS.md", "from the Part C template", data=(parts["c1"] + "\n").encode("utf-8"))
        if not os.path.isfile(os.path.join(project, "docs", "CURRENT_OPS-archive.md")):
            item("create", "docs/CURRENT_OPS-archive.md", "from the Part C template", data=(parts["c2"] + "\n").encode("utf-8"))

    # receipt
    ver = src.label
    receipt = dict(source=ver, tools=sorted(tools), modules=sorted(modules), shell=a.shell, visibility=a.visibility,
                   policy=a.policy, files={k: sha(v) for k, v in sorted(files.items())})
    rb = dumps(receipt).encode("utf-8")
    cur = None
    rp = os.path.join(project, *RECEIPT.split("/"))
    if os.path.isfile(rp):
        with open(rp, "rb") as f:
            cur = f.read()
    if cur == rb:
        item("unchanged", RECEIPT, "install receipt")
    else:
        item("create" if cur is None else "update", RECEIPT, "install receipt", data=rb)
    return project, plan


def main(argv=None):
    ap = argparse.ArgumentParser(description="genai-agentic-ops installer (dry run unless --apply)")
    ap.add_argument("--tools", default="", help="comma list of: " + ",".join(TOOLS))
    ap.add_argument("--modules", default="guard,githooks,scripts", help="comma list of: " + ",".join(MODULES))
    ap.add_argument("--shell", choices=SHELLS, default="ps" if os.name == "nt" else "sh")
    ap.add_argument("--visibility", choices=("hidden", "visible"), default="hidden")
    ap.add_argument("--policy", choices=("agent-commits", "user-only-git"), default="agent-commits")
    ap.add_argument("--remote", default="", help="overlay remote (URL or name) for hidden mode; default the project's origin")
    ap.add_argument("--kit-dir", default="", help="local kit folder (default: the folder of this file)")
    ap.add_argument("--pin", default="", help="commit sha to download the kit from")
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files that differ")
    ap.add_argument("--local-only", action="store_true", help="hidden mode without an overlay remote")
    ap.add_argument("--skip-sync", action="store_true", help="hidden mode: do not run agentic-sync init")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        if a.pin and a.kit_dir:
            raise Fail(2, "use either --kit-dir or --pin")
        src = RemoteSource(a.pin) if a.pin else LocalSource(a.kit_dir or os.path.dirname(os.path.abspath(__file__)))
        project, plan = build_plan(a, src)
        print(f"genai-agentic-ops install ({'APPLY' if a.apply else 'dry run'}) into {project}")
        print(f"  tools={a.tools or '-'} modules={a.modules} shell={a.shell} visibility={a.visibility} policy={a.policy} source={src.label}")
        print_plan(plan, a.apply)
        if "antigravity" in (a.tools or "").split(","):
            print("  note: Antigravity reads .agents/hooks.json from the folder opened as the workspace. "
                  "Open the repository root itself, not a parent folder, or the guard hook does not load.")
        blocked = [p for p in plan if p["action"] == "stop" or (p["action"] == "conflict" and not a.force)]
        if blocked:
            stops = [p for p in plan if p["action"] == "stop"]
            for p in stops:
                print(f"  STOP {p['path']}: {p['detail']}")
            if any(p["action"] == "conflict" for p in blocked):
                print("  Existing files differ from the kit. Review the diffs above; --force overwrites them (back them up first).")
            if a.apply:
                print("Nothing was written.")
            return 4
        if not a.apply:
            print("Dry run: nothing was written. Re-run with --apply to install.")
            return 0
        changed = [p for p in plan if p["action"] not in ("unchanged", "skip")]
        apply_plan(project, plan, a.force)
        if not changed:
            print("Nothing to do: everything is already installed and up to date.")
        else:
            print(f"Installed {len(changed)} file(s). Nothing was committed or pushed.")
        if a.visibility == "hidden" and not a.skip_sync:
            code = run_sync(a, project)
            if code != 0:
                print(f"agentic-sync init stopped with exit code {code} (3 tracked, 4 local files differ, 5 overlay dirty or diverged, 6 remote unreachable).")
                return 5
        if "githooks" in a.modules.split(",") and a.visibility == "visible":
            _, hp = git(project, "config", "--get", "core.hooksPath")
            if not hp:
                git(project, "config", "core.hooksPath", ".githooks")
                print("  set core.hooksPath=.githooks")
            elif hp != ".githooks":
                print(f"  warning: core.hooksPath is {hp!r}; the kit hooks in .githooks are not active")
        return 0
    except Fail as e:
        print(f"install: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
