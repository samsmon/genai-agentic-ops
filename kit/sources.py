"""Source resolving, manifest downloading, and template merging helpers for kit/install.py."""
import difflib
import hashlib
import json
import os
import re
import subprocess
import urllib.request

RAW_BASE = os.environ.get("AGENTIC_OPS_RAW_BASE", "https://raw.githubusercontent.com/samsmon/genai-agentic-ops")
SYNC_EXT = {"ps": "ps1", "sh": "sh"}


class Fail(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class LocalSource:
    def __init__(self, kit_dir):
        self.kit_dir = os.path.abspath(kit_dir)
        self.label = "local:" + self.kit_dir

    def kit(self, rel):
        with open(os.path.join(self.kit_dir, *rel.split("/")), "rb") as f:
            return f.read()

    def root(self, rel):
        with open(os.path.join(os.path.dirname(self.kit_dir), *rel.split("/")), "rb") as f:
            return f.read()


class RemoteSource:
    def __init__(self, pin):
        self.pin, self.label = pin, "pin:" + pin

    def _get(self, rel):
        url = f"{RAW_BASE}/{self.pin}/{rel}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "agentic-ops-install"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            raise Fail(6, f"cannot fetch {url}: {e}")

    def kit(self, rel):
        return self._get("kit/" + rel)

    def root(self, rel):
        return self._get(rel)


def git(project, *args):
    r = subprocess.run(
        ["git", "-C", project] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, r.stdout.strip()


def parse_manifest(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != 4:
            raise Fail(2, f"bad MANIFEST line: {line}")
        out.append(dict(group=parts[0], mode=parts[1], src=parts[2], dst=parts[3]))
    return out


def select(entries, tools, modules, shell):
    want = set()
    if "guard" in modules and tools:
        want.add("core")
        want.update("tool:" + t for t in tools)
    if "githooks" in modules:
        want.add("githooks")
    if "scripts" in modules:
        want.update(("scripts", "scripts:" + shell))
    if "handoff" in modules:
        want.add("handoff:" + shell)
    if "tests" in modules:
        want.update(("tests", "tests:" + shell))
    seen, out = set(), []
    for e in entries:
        if e["group"] in want and e["dst"] not in seen:
            seen.add(e["dst"])
            out.append(e)
    return out


def fences(text, heading_re):
    m = re.search(heading_re + r".*?```markdown\n(.*?)\n```", text, re.S)
    if not m:
        raise Fail(2, "RULES.md: section not found: " + heading_re)
    return m.group(1)


def rules_parts(rules_text):
    t = rules_text.replace("\r\n", "\n")
    m = re.search(r"```markdown\n(<!-- BEGIN genai-agentic-ops v2 -->.*?<!-- END genai-agentic-ops v2 -->)\n```", t, re.S)
    if not m:
        raise Fail(2, "RULES.md: Part B block not found")
    return dict(block=m.group(1), b1=fences(t, r"### B1"), b2=fences(t, r"### B2"), b3=fences(t, r"### B3"),
                b4=fences(t, r"### B4"), c1=fences(t, r"## C1"), c2=fences(t, r"## C2"))


def compose_block(parts, policy, hidden, handoff):
    pol = parts["b2"] if policy == "agent-commits" else parts["b1"]
    if hidden:
        pol = pol + "\n" + parts["b4"]
    blk = parts["block"].replace("<!-- GIT-POLICY -->", pol)
    if handoff:
        end = "<!-- END genai-agentic-ops v2 -->"
        blk = blk.replace(end, parts["b3"] + "\n" + end)
    return blk


HEAD_RE = re.compile(r"^## Agent Rules \(genai-agentic-ops v\d+\)$", re.M)
BEGIN_RE = re.compile(r"^<!-- BEGIN genai-agentic-ops v\d+ -->\n?", re.M)
END_RE = re.compile(r"^<!-- END genai-agentic-ops v\d+ -->", re.M)


def merge_block(doc, blk):
    """Part A step 4. Returns (action, new_text, note); action is create|append|replace|unchanged|stop."""
    if doc is None:
        return "create", blk + "\n", "new file"
    nl = "\r\n" if "\r\n" in doc else "\n"
    text = doc.replace("\r\n", "\n")
    begin, end, head = BEGIN_RE.search(text), END_RE.search(text), HEAD_RE.search(text)
    if begin and end and begin.start() < end.start():
        new, note = text[:begin.start()] + blk + text[end.end():], "both markers: block replaced"
    elif end and not begin and head and head.start() < end.start():
        new, note = text[:head.start()] + blk + text[end.end():], "BEGIN marker was missing: replaced from the heading to END"
    elif begin or end or head:
        return "stop", None, ("damaged markers (BEGIN without END, END before BEGIN, or the heading with no markers): "
                              "the end of the block is unknown, fix it by hand or tell the user, then run again")
    else:
        new, note = text.rstrip("\n") + "\n\n" + blk + "\n", "no block yet: appended"
    if new == text:
        return "unchanged", doc, "block already up to date"
    return ("append" if note.startswith("no block") else "replace"), new.replace("\n", nl), note


def _cmds(item):
    out = []
    if isinstance(item, dict):
        if isinstance(item.get("command"), str):
            out.append(item["command"])
        for h in item.get("hooks") or []:
            out.extend(_cmds(h))
    return out


def _ours(item):
    return any(("guard.py" in c or "session_start.py" in c or "agentic-ops-guard" in c) for c in _cmds(item))


def merge_json(dst, src):
    if isinstance(dst, dict) and isinstance(src, dict):
        out = dict(dst)
        for k, v in src.items():
            if k not in out:
                out[k] = v
            elif k == "agentic-ops-guard":
                out[k] = v  # our own named hook: upgrade in place
            else:
                out[k] = merge_json(out[k], v)
        return out
    if isinstance(dst, list) and isinstance(src, list):
        out = list(dst)
        for item in src:
            if item in out:
                continue
            if isinstance(item, dict) and _ours(item):
                idx = [i for i, d in enumerate(out) if isinstance(d, dict) and _ours(d) and d.get("matcher") == item.get("matcher")]
                if idx:
                    out[idx[0]] = item
                    for i in reversed(idx[1:]):
                        del out[i]
                    continue
            out.append(item)
        return out
    return dst


def dumps(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def find_sh():
    import shutil
    p = shutil.which("sh")
    if p:
        return p
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if root:
            for rel in ("Git/bin/sh.exe", "Git/usr/bin/sh.exe"):
                c = os.path.join(root, *rel.split("/"))
                if os.path.isfile(c):
                    return c
    return None


def read_text(path):
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def short_diff(old, new, label):
    d = [l for l in difflib.unified_diff(old.splitlines(), new.splitlines(), "installed", "kit", lineterm="", n=0)
         if not l.startswith(("---", "+++"))]
    head = f"      {len(d)} differing line(s) in {label}"
    return "\n".join([head] + ["      " + l[:150] for l in d[:12]] + (["      ..."] if len(d) > 12 else []))


def print_plan(plan, applying):
    w = max(len(p["action"]) for p in plan)
    for p in plan:
        print(f"  {p['action']:<{w}}  {p['path']}" + (f"   ({p['detail']})" if p["detail"] and "\n" not in p["detail"] else ""))
        if p["action"] == "conflict" and "\n" in p["detail"]:
            print(p["detail"])
    counts = {}
    for p in plan:
        counts[p["action"]] = counts.get(p["action"], 0) + 1
    print("  " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))


def apply_plan(project, plan, force):
    for p in plan:
        if p["action"] in ("unchanged", "skip", "stop"):
            continue
        if p["action"] == "conflict" and not force:
            continue
        if p["data"] is None:
            continue
        dst = os.path.join(project, *p["path"].split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(p["data"])
        if p["mode"] == "copy-exec":
            try:
                os.chmod(dst, 0o755)
            except OSError:
                pass


def run_sync(a, project):
    script = os.path.join(project, "scripts", "agentic-ops", "agentic-sync." + SYNC_EXT[a.shell])
    if not os.path.isfile(script):
        raise Fail(2, "agentic-sync was not installed; hidden mode needs the scripts module")
    rc, remotes = git(project, "remote")
    local_only = a.local_only or (not remotes and not a.remote)
    if a.shell == "sh":
        sh = find_sh()
        if not sh:
            raise Fail(2, "sh not found (PATH or Git for Windows); install Git for Windows or use --shell ps")
        cmd = [sh, script, "init"] + (["--remote", a.remote] if a.remote else []) + (["--local-only"] if local_only else [])
    else:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "init"] + \
              (["-Remote", a.remote] if a.remote else []) + (["-LocalOnly"] if local_only else [])
    if local_only and not a.local_only:
        print("  note: no git remote configured, hidden mode runs --local-only (add a remote or pass --remote, then run init again)")
    r = subprocess.run(cmd, cwd=project)
    return r.returncode
