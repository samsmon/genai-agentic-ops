"""Structure checks for RULES.md and a reference run of the Part A marker rules. Run: python -I kit/tests/test_rules_block.py"""
import os
import re

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "RULES.md")
fail = 0


def expect(name, ok):
    global fail
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fail += 1


text = open(RULES, encoding="utf-8").read().replace("\r\n", "\n")
m = re.search(r"```markdown\n(<!-- BEGIN genai-agentic-ops v2 -->.*?<!-- END genai-agentic-ops v2 -->)\n```", text, re.S)
block = m.group(1) if m else ""
b1 = re.search(r"### B1.*?```markdown\n(.*?)\n```", text, re.S)
b2 = re.search(r"### B2.*?```markdown\n(.*?)\n```", text, re.S)
new = block.replace("<!-- GIT-POLICY -->", b1.group(1)) if (block and b1) else ""

expect("rules block found", bool(block))
expect("exactly one GIT-POLICY placeholder", block.count("<!-- GIT-POLICY -->") == 1)
expect("snippets B1 and B2 found", bool(b1 and b2))
expect("block has one BEGIN and one END", block.count("BEGIN genai-agentic-ops") == 1 and block.count("END genai-agentic-ops") == 1)
expect("no v1 marker left in block", "genai-agentic-ops v1" not in block)

HEAD = re.compile(r"^## Agent Rules \(genai-agentic-ops v\d+\)$", re.M)


def apply_block(doc, blk):
    """Reference implementation of Part A step 4. Returns the new text, or None when the agent must ask the user."""
    begin = re.search(r"^<!-- BEGIN genai-agentic-ops v\d+ -->\n?", doc, re.M)
    end = re.search(r"^<!-- END genai-agentic-ops v\d+ -->", doc, re.M)
    head = HEAD.search(doc)
    if begin and end and begin.start() < end.start():
        return doc[:begin.start()] + blk + doc[end.end():]
    if end and not begin and head and head.start() < end.start():
        return doc[:head.start()] + blk + doc[end.end():]
    if begin or end or head:
        return None
    return doc.rstrip("\n") + "\n\n" + blk + "\n"


old_body = "## Agent Rules (genai-agentic-ops v1)\n\n### 0. Session start\n- old rule\n"
pre, post = "# Project\n\nOwn rules.\n\n", "\n## Other section\nkeep me\n"
full = pre + "<!-- BEGIN genai-agentic-ops v1 -->\n" + old_body + "<!-- END genai-agentic-ops v1 -->" + post
orphan = pre + old_body + "<!-- END genai-agentic-ops v1 -->" + post
no_end = pre + "<!-- BEGIN genai-agentic-ops v1 -->\n" + old_body + post
no_markers = pre + old_body + post

for name, doc in (("both markers", full), ("END without BEGIN", orphan)):
    out = apply_block(doc, new)
    expect(f"{name}: one v2 block, no v1 left", out is not None and out.count("BEGIN genai-agentic-ops v2") == 1 and "genai-agentic-ops v1" not in out)
    expect(f"{name}: surrounding text untouched", out is not None and out.startswith(pre) and out.endswith(post))
    expect(f"{name}: idempotent", out is not None and apply_block(out, new) == out)

expect("BEGIN without END: asks the user", apply_block(no_end, new) is None)
expect("heading without markers: asks the user", apply_block(no_markers, new) is None)
appended = apply_block("# Project\n\nOwn rules.\n", new)
expect("no block at all: appended once", appended is not None and appended.count("BEGIN genai-agentic-ops v2") == 1 and appended.startswith("# Project"))

print(f"[TESTS] {fail} failed")
raise SystemExit(1 if fail else 0)
